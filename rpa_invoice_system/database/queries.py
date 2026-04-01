"""Reusable database query helpers."""
from datetime import datetime, date
from typing import List, Optional

from sqlalchemy.orm import Session

from database.models import AuditLog, CorrectionHistory, Invoice, InvoiceLineItem, InvoiceStatus


# ── Invoice CRUD ─────────────────────────────────────────────────────────────

def create_invoice(db: Session, data: dict) -> Invoice:
    line_items_data = data.pop("line_items", [])
    invoice = Invoice(**data)
    db.add(invoice)
    db.flush()  # get ID before adding children

    for idx, item in enumerate(line_items_data, start=1):
        item["invoice_id"] = invoice.id
        item.setdefault("line_number", idx)
        db.add(InvoiceLineItem(**item))

    return invoice


def get_invoice(db: Session, invoice_id: int) -> Optional[Invoice]:
    return db.query(Invoice).filter(Invoice.id == invoice_id).first()


def get_invoices_by_status(db: Session, status: InvoiceStatus) -> List[Invoice]:
    return db.query(Invoice).filter(Invoice.status == status).order_by(Invoice.received_at.desc()).all()


def get_all_invoices(db: Session, limit: int = 200, offset: int = 0) -> List[Invoice]:
    return (
        db.query(Invoice)
        .order_by(Invoice.received_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def update_invoice_status(db: Session, invoice_id: int, status: InvoiceStatus, actor: str = "system") -> Optional[Invoice]:
    invoice = get_invoice(db, invoice_id)
    if invoice:
        invoice.status = status
        if status in (InvoiceStatus.AUTO_APPROVED, InvoiceStatus.HUMAN_APPROVED, InvoiceStatus.REJECTED):
            invoice.reviewed_at = datetime.utcnow()
            invoice.approved_by = actor
    return invoice


def update_invoice_fields(db: Session, invoice_id: int, fields: dict, corrected_by: str) -> Optional[Invoice]:
    invoice = get_invoice(db, invoice_id)
    if not invoice:
        return None

    for field, new_value in fields.items():
        old_value = getattr(invoice, field, None)
        setattr(invoice, field, new_value)
        db.add(CorrectionHistory(
            invoice_id=invoice_id,
            corrected_by=corrected_by,
            field_name=field,
            old_value=str(old_value),
            new_value=str(new_value),
        ))

    return invoice


# ── Duplicate detection ───────────────────────────────────────────────────────

def find_duplicate(
    db: Session,
    vendor_name: str,
    invoice_number: str,
    grand_total: float,
    exclude_id: int = None,
) -> Optional[Invoice]:
    q = (
        db.query(Invoice)
        .filter(
            Invoice.vendor_name == vendor_name,
            Invoice.invoice_number == invoice_number,
            Invoice.grand_total == grand_total,
            Invoice.status != InvoiceStatus.REJECTED,
        )
    )
    if exclude_id is not None:
        q = q.filter(Invoice.id != exclude_id)
    return q.first()


# ── Audit log ─────────────────────────────────────────────────────────────────

def add_audit_log(
    db: Session,
    invoice_id: int,
    action: str,
    detail: str = "",
    result: str = "SUCCESS",
    actor: str = "system",
):
    log = AuditLog(
        invoice_id=invoice_id,
        action=action,
        actor=actor,
        detail=detail,
        result=result,
    )
    db.add(log)


# ── Daily summary stats ───────────────────────────────────────────────────────

def get_daily_stats(db: Session, target_date: date) -> dict:
    start = datetime(target_date.year, target_date.month, target_date.day)
    end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

    invoices = (
        db.query(Invoice)
        .filter(Invoice.received_at >= start, Invoice.received_at <= end)
        .all()
    )

    status_counts = {}
    for inv in invoices:
        key = inv.status.value if inv.status else "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1

    vendor_counts = {}
    for inv in invoices:
        v = inv.vendor_name or "Unknown"
        vendor_counts[v] = vendor_counts.get(v, 0) + 1

    errors = []
    for inv in invoices:
        if inv.validation_errors:
            errors.extend([e.get("type", "unknown") for e in inv.validation_errors])

    error_counts = {}
    for e in errors:
        error_counts[e] = error_counts.get(e, 0) + 1

    return {
        "date": target_date.isoformat(),
        "total": len(invoices),
        "status_breakdown": status_counts,
        "vendor_breakdown": vendor_counts,
        "error_type_counts": error_counts,
        "auto_approved": status_counts.get("auto_approved", 0),
        "flagged": status_counts.get("flagged", 0),
        "human_approved": status_counts.get("human_approved", 0),
        "rejected": status_counts.get("rejected", 0),
    }
