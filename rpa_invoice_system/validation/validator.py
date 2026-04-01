"""
InvoiceValidator — runs all business-rule checks on an extracted invoice dict.

Returns a ValidationResult with:
  - errors:   blocking issues (invoice will be flagged)
  - warnings: non-blocking advisory notes
  - is_valid: True only when no errors exist
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fuzzywuzzy import fuzz

from config import config

logger = logging.getLogger(__name__)

MATH_TOLERANCE = 0.02  # $0.02 rounding tolerance


@dataclass
class ValidationResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, type_: str, message: str, field: str = ""):
        self.errors.append({"type": type_, "message": message, "field": field})
        logger.warning("VALIDATION ERROR [%s]: %s", type_, message)

    def add_warning(self, type_: str, message: str, field: str = ""):
        self.warnings.append({"type": type_, "message": message, "field": field})
        logger.info("VALIDATION WARNING [%s]: %s", type_, message)


class InvoiceValidator:
    def __init__(self):
        self._vendors_df: Optional[pd.DataFrame] = None
        self._pos_df: Optional[pd.DataFrame] = None
        self._load_reference_data()

    def _load_reference_data(self):
        try:
            if config.VENDORS_CSV.exists():
                self._vendors_df = pd.read_csv(config.VENDORS_CSV, dtype=str).fillna("")
                logger.info("Loaded %d vendors.", len(self._vendors_df))
        except Exception as exc:
            logger.error("Could not load vendors CSV: %s", exc)

        try:
            if config.PURCHASE_ORDERS_CSV.exists():
                self._pos_df = pd.read_csv(config.PURCHASE_ORDERS_CSV, dtype=str).fillna("")
                logger.info("Loaded %d purchase orders.", len(self._pos_df))
        except Exception as exc:
            logger.error("Could not load POs CSV: %s", exc)

    def reload_reference_data(self):
        self._load_reference_data()

    def validate(self, data: dict, db_session=None, exclude_id: int = None) -> ValidationResult:
        result = ValidationResult()

        self._check_required_fields(data, result)
        self._check_math(data, result)
        self._check_dates(data, result)
        self._check_vendor(data, result)
        self._check_po(data, result)
        self._check_amount_threshold(data, result)
        self._check_duplicate(data, result, db_session, exclude_id)
        self._check_confidence(data, result)

        return result

    # ── Required fields ───────────────────────────────────────────────────────

    def _check_required_fields(self, data: dict, result: ValidationResult):
        required = {
            "invoice_number": "Invoice Number",
            "vendor_name": "Vendor Name",
            "invoice_date": "Invoice Date",
            "grand_total": "Grand Total",
        }
        for field_key, label in required.items():
            if not data.get(field_key):
                result.add_error("MISSING_FIELD", f"Required field missing: {label}", field_key)

    # ── Math validation ───────────────────────────────────────────────────────

    def _check_math(self, data: dict, result: ValidationResult):
        line_items = data.get("line_items", [])
        subtotal = data.get("subtotal")
        tax = data.get("tax_amount") or 0.0
        grand_total = data.get("grand_total")

        # Line item arithmetic
        line_total_sum = 0.0
        for i, item in enumerate(line_items, start=1):
            qty = item.get("quantity")
            up = item.get("unit_price")
            lt = item.get("line_total")

            if qty is not None and up is not None and lt is not None:
                expected = round(qty * up, 2)
                if abs(expected - lt) > MATH_TOLERANCE:
                    result.add_error(
                        "LINE_ITEM_MATH",
                        f"Line {i}: {qty} × {up} = {expected}, but recorded as {lt}",
                        f"line_items[{i}].line_total",
                    )
            if lt is not None:
                line_total_sum += lt

        # Sum of lines vs subtotal
        if line_items and subtotal is not None and line_total_sum > 0:
            if abs(line_total_sum - subtotal) > MATH_TOLERANCE:
                result.add_error(
                    "SUBTOTAL_MISMATCH",
                    f"Sum of line items ({line_total_sum:.2f}) ≠ subtotal ({subtotal:.2f})",
                    "subtotal",
                )

        # Subtotal + tax = grand total
        if subtotal is not None and grand_total is not None:
            expected_total = round(subtotal + tax, 2)
            if abs(expected_total - grand_total) > MATH_TOLERANCE:
                result.add_error(
                    "GRAND_TOTAL_MISMATCH",
                    f"Subtotal ({subtotal:.2f}) + Tax ({tax:.2f}) = {expected_total:.2f}, "
                    f"but grand total is {grand_total:.2f}",
                    "grand_total",
                )

    # ── Date validation ───────────────────────────────────────────────────────

    def _check_dates(self, data: dict, result: ValidationResult):
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        inv_date = data.get("invoice_date")
        due_date = data.get("due_date")

        if inv_date:
            if inv_date > now:
                result.add_error(
                    "FUTURE_INVOICE_DATE",
                    f"Invoice date ({inv_date.date()}) is in the future.",
                    "invoice_date",
                )
            days_old = (now - inv_date).days
            if days_old > 365:
                result.add_warning(
                    "OLD_INVOICE_DATE",
                    f"Invoice date ({inv_date.date()}) is over 1 year old ({days_old} days).",
                    "invoice_date",
                )

        if due_date and inv_date:
            if due_date < inv_date:
                result.add_error(
                    "DUE_BEFORE_INVOICE",
                    f"Due date ({due_date.date()}) is before invoice date ({inv_date.date()}).",
                    "due_date",
                )

        if due_date and due_date < now:
            result.add_warning(
                "PAST_DUE",
                f"Invoice is past due (due {due_date.date()}).",
                "due_date",
            )

    # ── Vendor verification ───────────────────────────────────────────────────

    def _check_vendor(self, data: dict, result: ValidationResult):
        vendor_name = data.get("vendor_name", "")
        vendor_id = data.get("vendor_id", "")

        if self._vendors_df is None or vendor_name == "":
            return

        # Exact match on vendor_id
        if vendor_id:
            id_col = self._col(self._vendors_df, "vendor_id")
            if id_col and vendor_id in self._vendors_df[id_col].values:
                return  # matched by ID, all good

        # Fuzzy match on name
        name_col = self._col(self._vendors_df, "vendor_name")
        if name_col is None:
            return

        best_score = 0
        best_match = ""
        for vname in self._vendors_df[name_col]:
            score = fuzz.token_sort_ratio(vendor_name.lower(), str(vname).lower())
            if score > best_score:
                best_score = score
                best_match = vname

        if best_score < 70:
            result.add_error(
                "UNKNOWN_VENDOR",
                f"Vendor '{vendor_name}' not found in master list "
                f"(closest match: '{best_match}' at {best_score}%).",
                "vendor_name",
            )
        elif best_score < 90:
            result.add_warning(
                "FUZZY_VENDOR_MATCH",
                f"Vendor '{vendor_name}' fuzzy-matched to '{best_match}' ({best_score}%). "
                "Verify vendor name.",
                "vendor_name",
            )

    # ── PO matching ──────────────────────────────────────────────────────────

    def _check_po(self, data: dict, result: ValidationResult):
        po_number = data.get("po_number", "")

        if not po_number:
            result.add_warning(
                "MISSING_PO",
                "No PO number found on this invoice.",
                "po_number",
            )
            return

        if self._pos_df is None:
            return

        po_col = self._col(self._pos_df, "po_number")
        if po_col is None:
            return

        open_col = self._col(self._pos_df, "status")
        row = self._pos_df[self._pos_df[po_col].str.upper() == po_number.upper()]

        if row.empty:
            result.add_error(
                "PO_NOT_FOUND",
                f"PO number '{po_number}' not found in open purchase orders.",
                "po_number",
            )
        elif open_col and not row.empty:
            status = str(row.iloc[0][open_col]).lower()
            if status in ("closed", "cancelled", "canceled"):
                result.add_error(
                    "PO_CLOSED",
                    f"PO number '{po_number}' is {status.upper()} — cannot accept new invoices.",
                    "po_number",
                )

    # ── Amount threshold ──────────────────────────────────────────────────────

    def _check_amount_threshold(self, data: dict, result: ValidationResult):
        total = data.get("grand_total")
        if total and total > config.AMOUNT_THRESHOLD:
            result.add_warning(
                "HIGH_VALUE",
                f"Invoice grand total ${total:,.2f} exceeds threshold "
                f"${config.AMOUNT_THRESHOLD:,.2f}. Requires human review.",
                "grand_total",
            )

    # ── Duplicate detection ───────────────────────────────────────────────────

    def _check_duplicate(self, data: dict, result: ValidationResult, db_session, exclude_id: int = None):
        if db_session is None:
            return

        vendor = data.get("vendor_name")
        inv_num = data.get("invoice_number")
        total = data.get("grand_total")

        if not (vendor and inv_num and total):
            return

        from database.queries import find_duplicate
        dup = find_duplicate(db_session, vendor, inv_num, total, exclude_id=exclude_id)
        if dup:
            result.add_error(
                "DUPLICATE_INVOICE",
                f"Duplicate detected: Invoice #{inv_num} from {vendor} "
                f"(${total:,.2f}) already exists as invoice ID {dup.id}.",
                "invoice_number",
            )

    # ── Low-confidence flag ───────────────────────────────────────────────────

    def _check_confidence(self, data: dict, result: ValidationResult):
        overall = data.get("_overall_confidence", 1.0)
        low_fields = data.get("_low_confidence_fields", [])

        if overall < config.CONFIDENCE_THRESHOLD:
            result.add_warning(
                "LOW_CONFIDENCE",
                f"Overall extraction confidence is {overall:.0%}. "
                f"Low-confidence fields: {', '.join(low_fields) or 'none'}.",
                "_overall_confidence",
            )

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _col(df: pd.DataFrame, name: str) -> Optional[str]:
        """Find a column by lowercase/underscore-normalised name."""
        for c in df.columns:
            if c.lower().replace(" ", "_") == name:
                return c
        return None
