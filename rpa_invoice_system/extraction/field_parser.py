"""
Regex + heuristic patterns to extract structured fields from raw invoice text.
Each extractor returns (value, confidence_score 0-1).
"""
import re
import logging
from datetime import datetime
from typing import Any, Optional, Tuple

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

# ── Compiled regex patterns ───────────────────────────────────────────────────

_INVOICE_NUM = re.compile(
    r"invoice\s*(?:no|num|number|#)?\s*[:#]\s*([A-Z0-9][A-Z0-9\-_/]{2,30})",
    re.IGNORECASE,
)

_PO_NUM = re.compile(
    r"(?:p\.?o\.?\s*(?:number|num|no|#)?\s*[:#]\s*|purchase\s+order\s*[:#]\s*)"
    r"([A-Z0-9][A-Z0-9\-_/]{2,30})",
    re.IGNORECASE,
)

_VENDOR_ID = re.compile(
    r"(?:vendor\s*(?:id|no|code|number)\s*[:#]\s*)"
    r"([A-Z0-9\-_]{2,20})",
    re.IGNORECASE,
)

# Handles MM/DD/YYYY, DD-MM-YYYY, YYYY-MM-DD, and month-name formats
_DATE_STR = (
    r"(\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}"          # YYYY-MM-DD
    r"|\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"         # MM/DD/YY or DD-MM-YYYY
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2},?\s+\d{4})"
)

_DATE_LABELS = re.compile(
    r"(?:invoice\s*date|date\s*of\s*invoice|bill\s*date)\s*[:#]?\s*" + _DATE_STR,
    re.IGNORECASE,
)

_DUE_DATE = re.compile(
    r"(?:due\s*date|payment\s*due|due\s*by)\s*[:#]?\s*" + _DATE_STR,
    re.IGNORECASE,
)

_PAYMENT_TERMS = re.compile(
    r"(?:payment\s*terms?|terms?)\s*[:#]\s*(net\s*\d+|due\s*on\s*receipt|immediate|net\s*eom|\d+\s*days?)",
    re.IGNORECASE,
)

_AMOUNT = re.compile(r"[\$£€]?\s*([\d,]+\.\d{2})")

_SUBTOTAL = re.compile(
    r"(?:subtotal|sub\s*total|net\s*amount)\s*[:#]?\s*[\$£€]?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)

_TAX = re.compile(
    r"(?:tax|vat|gst|hst|sales\s*tax)\s*[^:\n]{0,15}[:#]\s*[\$£€]?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)

# Require explicit "grand" or "due" prefix to avoid matching subtotal's "total"
_GRAND_TOTAL = re.compile(
    r"(?:grand\s*total|total\s*due|total\s*amount\s*due|amount\s*due)\s*[:#]?\s*[\$£€]?\s*([\d,]+\.\d{2})",
    re.IGNORECASE,
)

_VENDOR_NAME_AFTER_FROM = re.compile(
    r"(?:from|bill\s*from|vendor)[:\s]+([A-Za-z0-9 ,\.&']{3,60})",
    re.IGNORECASE,
)


def _parse_amount(text: str) -> Optional[float]:
    m = _AMOUNT.search(text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_date(text: str) -> Optional[datetime]:
    text = text.strip()
    try:
        return dateutil_parser.parse(text, dayfirst=False)
    except Exception:
        return None


def extract_invoice_number(text: str) -> Tuple[Optional[str], float]:
    m = _INVOICE_NUM.search(text)
    if m:
        return m.group(1).strip(), 0.90
    # Fallback: look for INV- prefix anywhere
    m2 = re.search(r"\b(INV[-_]?\d{3,10})\b", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip(), 0.75
    return None, 0.0


def extract_po_number(text: str) -> Tuple[Optional[str], float]:
    m = _PO_NUM.search(text)
    if m:
        return m.group(1).strip(), 0.88
    m2 = re.search(r"\b(PO[-_]?\d{3,10})\b", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip(), 0.70
    return None, 0.0


def extract_vendor_id(text: str) -> Tuple[Optional[str], float]:
    m = _VENDOR_ID.search(text)
    if m:
        return m.group(1).strip(), 0.85
    return None, 0.0


def extract_vendor_name(text: str) -> Tuple[Optional[str], float]:
    m = _VENDOR_NAME_AFTER_FROM.search(text)
    if m:
        name = m.group(1).strip().rstrip(",.")
        return name, 0.70
    # Heuristic: first non-empty line that isn't a date or number often is vendor
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:5]:
        if re.match(r"^[A-Za-z][\w\s,\.&']{5,50}$", line) and not re.search(r"\d{4}", line):
            return line, 0.50
    return None, 0.0


def extract_invoice_date(text: str) -> Tuple[Optional[datetime], float]:
    m = _DATE_LABELS.search(text)
    if m:
        dt = _parse_date(m.group(1))
        if dt:
            return dt, 0.88
    return None, 0.0


def extract_due_date(text: str) -> Tuple[Optional[datetime], float]:
    m = _DUE_DATE.search(text)
    if m:
        dt = _parse_date(m.group(1))
        if dt:
            return dt, 0.85
    return None, 0.0


def extract_payment_terms(text: str) -> Tuple[Optional[str], float]:
    m = _PAYMENT_TERMS.search(text)
    if m:
        return m.group(1).strip(), 0.82
    return None, 0.0


def extract_subtotal(text: str) -> Tuple[Optional[float], float]:
    m = _SUBTOTAL.search(text)
    if m:
        return float(m.group(1).replace(",", "")), 0.88
    return None, 0.0


def extract_tax(text: str) -> Tuple[Optional[float], float]:
    m = _TAX.search(text)
    if m:
        return float(m.group(1).replace(",", "")), 0.85
    return None, 0.0


def extract_grand_total(text: str) -> Tuple[Optional[float], float]:
    m = _GRAND_TOTAL.search(text)
    if m:
        return float(m.group(1).replace(",", "")), 0.90
    return None, 0.0


def extract_line_items(text: str) -> Tuple[list, float]:
    """
    Attempt to extract tabular line items from text.
    Pattern: optional SKU, description, qty, unit price, total on same line.
    Returns list of dicts and overall confidence.
    """
    # Pattern: description  qty  unit_price  total (tab or multi-space separated)
    pattern = re.compile(
        r"^(.{3,50}?)\s{2,}"          # description
        r"(\d+(?:\.\d+)?)\s+"          # quantity
        r"[\$£€]?\s*([\d,]+\.\d{2})\s+"  # unit price
        r"[\$£€]?\s*([\d,]+\.\d{2})",  # line total
        re.MULTILINE,
    )

    items = []
    for m in pattern.finditer(text):
        desc = m.group(1).strip()
        # Skip header rows
        if re.search(r"description|qty|quantity|price|amount", desc, re.IGNORECASE):
            continue
        items.append({
            "description": desc,
            "quantity": float(m.group(2)),
            "unit_price": float(m.group(3).replace(",", "")),
            "line_total": float(m.group(4).replace(",", "")),
        })

    if items:
        return items, 0.80
    return [], 0.0


def parse_all_fields(text: str) -> dict:
    """Run all extractors and return a unified dict with confidence scores."""
    results = {}
    low_confidence = []
    scores = []

    def _add(key, extractor, *args):
        val, conf = extractor(*args)
        results[key] = val
        results[f"_conf_{key}"] = conf
        scores.append(conf)
        if val is not None and conf < 0.75:
            low_confidence.append(key)

    _add("invoice_number", extract_invoice_number, text)
    _add("po_number", extract_po_number, text)
    _add("vendor_name", extract_vendor_name, text)
    _add("vendor_id", extract_vendor_id, text)
    _add("invoice_date", extract_invoice_date, text)
    _add("due_date", extract_due_date, text)
    _add("payment_terms", extract_payment_terms, text)
    _add("subtotal", extract_subtotal, text)
    _add("tax_amount", extract_tax, text)
    _add("grand_total", extract_grand_total, text)

    line_items, li_conf = extract_line_items(text)
    results["line_items"] = line_items
    results["_conf_line_items"] = li_conf
    if li_conf < 0.75:
        low_confidence.append("line_items")
    scores.append(li_conf)

    overall = sum(s for s in scores if s > 0) / max(1, sum(1 for s in scores if s > 0))
    results["_overall_confidence"] = round(overall, 3)
    results["_low_confidence_fields"] = low_confidence

    return results
