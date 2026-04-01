"""Tests for the validation engine."""
import pytest
from datetime import datetime, timedelta, timezone

from validation.validator import InvoiceValidator


@pytest.fixture
def validator():
    return InvoiceValidator()


def _base_invoice(**overrides):
    data = {
        "invoice_number": "INV-TEST-001",
        "vendor_name": "Acme Supplies Inc",
        "vendor_id": "V001",
        "po_number": "PO-2024-001",
        "invoice_date": datetime(2024, 3, 1),
        "due_date": datetime(2024, 3, 31),
        "payment_terms": "Net 30",
        "subtotal": 100.00,
        "tax_amount": 8.00,
        "grand_total": 108.00,
        "line_items": [
            {"description": "Widget", "quantity": 10, "unit_price": 10.00, "line_total": 100.00}
        ],
        "_overall_confidence": 0.95,
        "_low_confidence_fields": [],
    }
    data.update(overrides)
    return data


class TestRequiredFields:
    def test_clean_invoice_passes(self, validator):
        result = validator.validate(_base_invoice())
        assert result.is_valid

    def test_missing_invoice_number(self, validator):
        result = validator.validate(_base_invoice(invoice_number=None))
        types = [e["type"] for e in result.errors]
        assert "MISSING_FIELD" in types

    def test_missing_vendor(self, validator):
        result = validator.validate(_base_invoice(vendor_name=None))
        types = [e["type"] for e in result.errors]
        assert "MISSING_FIELD" in types

    def test_missing_total(self, validator):
        result = validator.validate(_base_invoice(grand_total=None))
        types = [e["type"] for e in result.errors]
        assert "MISSING_FIELD" in types


class TestMathValidation:
    def test_correct_math_passes(self, validator):
        result = validator.validate(_base_invoice())
        math_errors = [e for e in result.errors if "MATH" in e["type"] or "MISMATCH" in e["type"]]
        assert math_errors == []

    def test_line_item_math_error(self, validator):
        data = _base_invoice(line_items=[
            {"description": "Widget", "quantity": 10, "unit_price": 10.00, "line_total": 999.00}  # wrong
        ])
        result = validator.validate(data)
        types = [e["type"] for e in result.errors]
        assert "LINE_ITEM_MATH" in types

    def test_subtotal_mismatch(self, validator):
        data = _base_invoice(subtotal=999.00)  # wrong
        result = validator.validate(data)
        types = [e["type"] for e in result.errors]
        assert "SUBTOTAL_MISMATCH" in types or "GRAND_TOTAL_MISMATCH" in types

    def test_grand_total_mismatch(self, validator):
        data = _base_invoice(grand_total=999.99)  # subtotal+tax = 108.00 != 999.99
        result = validator.validate(data)
        types = [e["type"] for e in result.errors]
        assert "GRAND_TOTAL_MISMATCH" in types


class TestDateValidation:
    def test_future_invoice_date(self, validator):
        future = datetime.now() + timedelta(days=30)
        result = validator.validate(_base_invoice(invoice_date=future))
        types = [e["type"] for e in result.errors]
        assert "FUTURE_INVOICE_DATE" in types

    def test_due_before_invoice(self, validator):
        result = validator.validate(_base_invoice(
            invoice_date=datetime(2024, 3, 15),
            due_date=datetime(2024, 3, 1),  # before invoice
        ))
        types = [e["type"] for e in result.errors]
        assert "DUE_BEFORE_INVOICE" in types


class TestAmountThreshold:
    def test_high_value_warning(self, validator):
        data = _base_invoice(
            subtotal=14000.00, tax_amount=1120.00, grand_total=15120.00,
            line_items=[{"description": "Freight", "quantity": 1, "unit_price": 14000.00, "line_total": 14000.00}]
        )
        result = validator.validate(data)
        warn_types = [w["type"] for w in result.warnings]
        assert "HIGH_VALUE" in warn_types

    def test_normal_value_no_threshold_warning(self, validator):
        result = validator.validate(_base_invoice())
        warn_types = [w["type"] for w in result.warnings]
        assert "HIGH_VALUE" not in warn_types


class TestMissingPO:
    def test_missing_po_raises_warning(self, validator):
        result = validator.validate(_base_invoice(po_number=None))
        warn_types = [w["type"] for w in result.warnings]
        assert "MISSING_PO" in warn_types
