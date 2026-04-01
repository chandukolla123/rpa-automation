"""Tests for database models and query helpers."""
import pytest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Invoice, InvoiceLineItem, InvoiceStatus
from database.queries import (
    create_invoice, get_invoice, get_invoices_by_status,
    update_invoice_status, find_duplicate, add_audit_log, get_daily_stats,
)


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _sample_data(**overrides):
    base = {
        "invoice_number": "INV-TEST-001",
        "vendor_name": "Test Vendor",
        "vendor_id": "V001",
        "po_number": "PO-001",
        "invoice_date": datetime(2024, 3, 1),
        "due_date": datetime(2024, 3, 31),
        "subtotal": 100.00,
        "tax_amount": 8.00,
        "grand_total": 108.00,
        "source_file": "test_invoice.csv",
        "status": InvoiceStatus.PENDING,
        "received_at": datetime.utcnow(),
        "line_items": [
            {"description": "Widget A", "quantity": 5, "unit_price": 20.00, "line_total": 100.00}
        ],
    }
    base.update(overrides)
    return base


def test_create_invoice(db):
    inv = create_invoice(db, _sample_data())
    db.commit()
    assert inv.id is not None
    assert inv.invoice_number == "INV-TEST-001"
    assert len(inv.line_items) == 1


def test_get_invoice(db):
    inv = create_invoice(db, _sample_data(invoice_number="INV-GET-001"))
    db.commit()
    fetched = get_invoice(db, inv.id)
    assert fetched is not None
    assert fetched.invoice_number == "INV-GET-001"


def test_get_invoice_not_found(db):
    assert get_invoice(db, 99999) is None


def test_update_status(db):
    inv = create_invoice(db, _sample_data(invoice_number="INV-STATUS-001"))
    db.commit()
    updated = update_invoice_status(db, inv.id, InvoiceStatus.AUTO_APPROVED)
    db.commit()
    assert updated.status == InvoiceStatus.AUTO_APPROVED


def test_find_duplicate(db):
    data = _sample_data(invoice_number="INV-DUP-001", vendor_name="Dup Vendor", grand_total=500.00)
    inv = create_invoice(db, data)
    db.commit()
    dup = find_duplicate(db, "Dup Vendor", "INV-DUP-001", 500.00)
    assert dup is not None
    assert dup.id == inv.id


def test_no_duplicate_when_different_amount(db):
    create_invoice(db, _sample_data(invoice_number="INV-NODUP-001", vendor_name="NoDup Vendor", grand_total=200.00))
    db.commit()
    dup = find_duplicate(db, "NoDup Vendor", "INV-NODUP-001", 999.00)
    assert dup is None


def test_add_audit_log(db):
    inv = create_invoice(db, _sample_data(invoice_number="INV-AUDIT-001"))
    db.commit()
    add_audit_log(db, inv.id, "RECEIVED", "test detail", "SUCCESS")
    db.commit()
    logs = inv.audit_logs
    assert any(l.action == "RECEIVED" for l in logs)


def test_get_invoices_by_status(db):
    create_invoice(db, _sample_data(invoice_number="INV-FLAGGED-001",
                                     status=InvoiceStatus.FLAGGED))
    db.commit()
    flagged = get_invoices_by_status(db, InvoiceStatus.FLAGGED)
    assert len(flagged) >= 1


def test_invoice_to_dict(db):
    inv = create_invoice(db, _sample_data(invoice_number="INV-DICT-001"))
    db.commit()
    d = inv.to_dict()
    assert d["invoice_number"] == "INV-DICT-001"
    assert "grand_total" in d
    assert "status" in d
