"""
Core processing pipeline: extraction → validation → persistence → audit.
Runs synchronously; called from the file watcher callback or scheduler.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from database.connection import get_db
from database.models import InvoiceStatus
from database.queries import add_audit_log, create_invoice, update_invoice_status
from extraction.extractor import InvoiceExtractor
from validation.validator import InvoiceValidator

logger = logging.getLogger(__name__)

_extractor = InvoiceExtractor()
_validator = InvoiceValidator()


def process_invoice(file_path: Path, file_hash: str = "") -> Optional[int]:
    """
    Full pipeline for a single invoice file.
    Returns the database invoice ID on success, or None on failure.
    """
    logger.info("=== Processing: %s ===", file_path.name)

    # ── Step 1: Extract ───────────────────────────────────────────────────────
    try:
        data = _extractor.extract(file_path)
    except Exception as exc:
        logger.error("Extraction crashed for %s: %s", file_path.name, exc, exc_info=True)
        _save_failed(file_path, file_hash, str(exc))
        return None

    # ── Step 2: Persist (initial record) ─────────────────────────────────────
    with get_db() as db:
        invoice_data = {
            "invoice_number":       data.get("invoice_number"),
            "vendor_name":          data.get("vendor_name"),
            "vendor_id":            data.get("vendor_id"),
            "po_number":            data.get("po_number"),
            "invoice_date":         data.get("invoice_date"),
            "due_date":             data.get("due_date"),
            "payment_terms":        data.get("payment_terms"),
            "subtotal":             data.get("subtotal"),
            "tax_amount":           data.get("tax_amount"),
            "grand_total":          data.get("grand_total"),
            "source_file":          str(file_path),
            "source_file_type":     data.get("source_file_type"),
            "file_hash":            file_hash,
            "raw_text":             data.get("raw_text", "")[:10000],  # cap size
            "confidence_score":     data.get("_overall_confidence"),
            "low_confidence_fields": data.get("_low_confidence_fields", []),
            "status":               InvoiceStatus.PROCESSING,
            "received_at":          datetime.utcnow(),
            "line_items":           data.get("line_items", []),
        }

        invoice = create_invoice(db, invoice_data)
        invoice_id = invoice.id
        add_audit_log(db, invoice_id, "RECEIVED", f"File: {file_path.name}", "SUCCESS")
        add_audit_log(db, invoice_id, "EXTRACTED",
                      f"Confidence: {data.get('_overall_confidence', 0):.0%}",
                      "SUCCESS" if not data.get("_extraction_error") else "FAILURE")
        logger.info("Invoice record created: ID=%d", invoice_id)

    # ── Step 3: Validate ──────────────────────────────────────────────────────
    with get_db() as db:
        result = _validator.validate(data, db_session=db, exclude_id=invoice_id)

        # Determine final status
        has_high_value = any(
            w.get("type") == "HIGH_VALUE" for w in result.warnings
        )
        low_conf = (data.get("_overall_confidence") or 1.0) < 0.75

        if result.errors or has_high_value or low_conf:
            status = InvoiceStatus.FLAGGED
        else:
            status = InvoiceStatus.AUTO_APPROVED

        update_invoice_status(db, invoice_id, status)

        # Persist validation results
        from database.queries import get_invoice
        inv = get_invoice(db, invoice_id)
        inv.validation_errors = result.errors
        inv.validation_warnings = result.warnings
        inv.processed_at = datetime.utcnow()

        add_audit_log(
            db, invoice_id, "VALIDATED",
            f"Errors: {len(result.errors)}, Warnings: {len(result.warnings)}",
            "SUCCESS" if result.is_valid else "WARNING",
        )

        if status == InvoiceStatus.AUTO_APPROVED:
            add_audit_log(db, invoice_id, "AUTO_APPROVED", "All validations passed.", "SUCCESS")
        else:
            reasons = [e["type"] for e in result.errors] + \
                      [w["type"] for w in result.warnings if w["type"] in ("HIGH_VALUE",)]
            add_audit_log(db, invoice_id, "FLAGGED_FOR_REVIEW",
                          f"Reasons: {', '.join(reasons)}", "WARNING")

        logger.info("Invoice %d → %s (errors=%d, warnings=%d)",
                    invoice_id, status.value, len(result.errors), len(result.warnings))

    return invoice_id


def _save_failed(file_path: Path, file_hash: str, error: str):
    """Persist a minimal failed record so nothing is silently lost."""
    with get_db() as db:
        invoice = create_invoice(db, {
            "source_file": str(file_path),
            "source_file_type": file_path.suffix.lstrip("."),
            "file_hash": file_hash,
            "status": InvoiceStatus.FAILED,
            "raw_text": error[:2000],
            "received_at": datetime.utcnow(),
        })
        add_audit_log(db, invoice.id, "EXTRACTION_FAILED", error[:500], "FAILURE")
