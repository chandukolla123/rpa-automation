"""Tests for extraction field parser."""
import pytest
from pathlib import Path

from extraction.field_parser import (
    extract_invoice_number, extract_po_number, extract_vendor_name,
    extract_invoice_date, extract_grand_total, extract_subtotal, extract_tax,
    extract_line_items, parse_all_fields,
)
from extraction.extractor import InvoiceExtractor


SAMPLE_TEXT = """
INVOICE

From: Acme Supplies Inc
Vendor ID: V001

Invoice Number: INV-2024-0101
Invoice Date: 2024-03-01
Due Date: 2024-03-31
Payment Terms: Net 30
PO Number: PO-2024-001

Description                        Qty  Unit Price  Total
Copy Paper A4 (Box)                50   42.00       2100.00
Ballpoint Pens (Box)               30   14.00       420.00
Stapler Heavy Duty                 20   84.00       1680.00

Subtotal:   4200.00
Tax (8%):    336.00
Grand Total: 4536.00
"""


def test_invoice_number():
    val, conf = extract_invoice_number(SAMPLE_TEXT)
    assert val == "INV-2024-0101"
    assert conf >= 0.75


def test_po_number():
    val, conf = extract_po_number(SAMPLE_TEXT)
    assert val == "PO-2024-001"
    assert conf >= 0.75


def test_vendor_name():
    val, conf = extract_vendor_name(SAMPLE_TEXT)
    assert "Acme" in val


def test_invoice_date():
    val, conf = extract_invoice_date(SAMPLE_TEXT)
    assert val is not None
    assert val.year == 2024
    assert val.month == 3
    assert val.day == 1


def test_grand_total():
    val, conf = extract_grand_total(SAMPLE_TEXT)
    assert val == 4536.00
    assert conf >= 0.85


def test_subtotal():
    val, conf = extract_subtotal(SAMPLE_TEXT)
    assert val == 4200.00


def test_tax():
    val, conf = extract_tax(SAMPLE_TEXT)
    assert val == 336.00


def test_line_items():
    items, conf = extract_line_items(SAMPLE_TEXT)
    assert len(items) >= 2
    totals = [i["line_total"] for i in items]
    assert 2100.00 in totals


def test_parse_all_fields():
    result = parse_all_fields(SAMPLE_TEXT)
    assert result["invoice_number"] == "INV-2024-0101"
    assert result["grand_total"] == 4536.00
    assert "_overall_confidence" in result
    assert result["_overall_confidence"] > 0.5


def test_csv_extractor():
    extractor = InvoiceExtractor()
    sample = Path(__file__).parent.parent / "sample_data" / "invoice_01_clean.csv"
    if not sample.exists():
        pytest.skip("Sample data not found")
    result = extractor.extract(sample)
    assert result["invoice_number"] == "INV-2024-0101"
    assert result["vendor_name"] == "Acme Supplies Inc"
    assert result["grand_total"] == 4536.00
    assert len(result["line_items"]) == 3
