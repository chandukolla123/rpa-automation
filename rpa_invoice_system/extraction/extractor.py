"""
InvoiceExtractor — routes each file type to the right extraction strategy.
"""
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from config import config
from extraction.field_parser import parse_all_fields

logger = logging.getLogger(__name__)


class InvoiceExtractor:
    """
    Dispatches extraction based on file extension.
    Returns a parsed dict ready for validation.
    """

    def extract(self, file_path: Path) -> dict:
        ext = file_path.suffix.lower()
        logger.info("Extracting %s (%s)", file_path.name, ext)

        try:
            if ext == ".pdf":
                raw_text = self._extract_pdf(file_path)
            elif ext in (".jpg", ".jpeg", ".png"):
                raw_text = self._extract_image(file_path)
            elif ext in (".csv",):
                return self._extract_csv(file_path)
            elif ext in (".xlsx", ".xls"):
                return self._extract_excel(file_path)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            result = parse_all_fields(raw_text)
            result["raw_text"] = raw_text
            result["source_file"] = str(file_path)
            result["source_file_type"] = ext.lstrip(".")
            return result

        except Exception as exc:
            logger.error("Extraction failed for %s: %s", file_path.name, exc, exc_info=True)
            return {
                "raw_text": "",
                "source_file": str(file_path),
                "source_file_type": ext.lstrip("."),
                "_overall_confidence": 0.0,
                "_low_confidence_fields": ["all"],
                "_extraction_error": str(exc),
            }

    # ── PDF ──────────────────────────────────────────────────────────────────

    def _extract_pdf(self, path: Path) -> str:
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                    # Also try to extract tables
                    for table in page.extract_tables():
                        for row in table:
                            if row:
                                text_parts.append("\t".join(str(c or "") for c in row))
            text = "\n".join(text_parts)
            if text.strip():
                return text
        except ImportError:
            logger.warning("pdfplumber not installed, falling back to OCR for PDF.")
        except Exception as exc:
            logger.warning("pdfplumber failed for %s: %s. Trying OCR.", path.name, exc)

        # Fallback: convert PDF pages to images and OCR
        return self._ocr_pdf(path)

    def _ocr_pdf(self, path: Path) -> str:
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(path), dpi=200)
            texts = [self._tesseract_ocr(img) for img in images]
            return "\n".join(texts)
        except ImportError:
            raise RuntimeError("pdf2image not installed; cannot OCR PDF.")

    # ── Image ────────────────────────────────────────────────────────────────

    def _extract_image(self, path: Path) -> str:
        from PIL import Image
        img = Image.open(str(path))
        return self._tesseract_ocr(img)

    def _tesseract_ocr(self, image) -> str:
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
            return pytesseract.image_to_string(image, config="--psm 6")
        except ImportError:
            raise RuntimeError("pytesseract not installed.")

    # ── CSV ──────────────────────────────────────────────────────────────────

    def _extract_csv(self, path: Path) -> dict:
        df = pd.read_csv(path, dtype=str).fillna("")
        return self._structured_df_to_invoice(df, path, "csv")

    # ── Excel ─────────────────────────────────────────────────────────────────

    def _extract_excel(self, path: Path) -> dict:
        df = pd.read_excel(path, dtype=str).fillna("")
        return self._structured_df_to_invoice(df, path, "xlsx")

    # ── Structured file parser ────────────────────────────────────────────────

    def _structured_df_to_invoice(self, df: pd.DataFrame, path: Path, ftype: str) -> dict:
        """
        Handles structured CSV/Excel invoices.
        Expects columns (case-insensitive):
          invoice_number, vendor_name, vendor_id, po_number,
          invoice_date, due_date, payment_terms,
          subtotal, tax_amount, grand_total,
          [line_*: description, quantity, unit_price, line_total]
        """
        col_map = {c.lower().replace(" ", "_"): c for c in df.columns}

        def get(key, default=None):
            col = col_map.get(key)
            if col and len(df) > 0:
                vals = df[col].dropna()
                if len(vals) > 0:
                    return vals.iloc[0]
            return default

        def parse_float(val) -> Optional[float]:
            if val is None or str(val).strip() == "":
                return None
            try:
                return float(str(val).replace(",", "").replace("$", "").strip())
            except ValueError:
                return None

        def parse_date(val):
            if not val:
                return None
            from dateutil import parser as dp
            try:
                return dp.parse(str(val))
            except Exception:
                return None

        # --- Header row (row 0) for invoice-level fields ---
        invoice_number = get("invoice_number") or get("invoice_no") or get("invoice_num")
        vendor_name = get("vendor_name") or get("vendor")
        vendor_id = get("vendor_id") or get("vendor_code")
        po_number = get("po_number") or get("po_no") or get("purchase_order")
        invoice_date = parse_date(get("invoice_date") or get("date"))
        due_date = parse_date(get("due_date"))
        payment_terms = get("payment_terms") or get("terms")
        subtotal = parse_float(get("subtotal"))
        tax_amount = parse_float(get("tax_amount") or get("tax"))
        grand_total = parse_float(get("grand_total") or get("total") or get("total_amount"))

        # --- Line items ---
        line_items = []
        has_line_cols = any(k in col_map for k in ("description", "quantity", "unit_price", "line_total"))
        if has_line_cols:
            for _, row in df.iterrows():
                desc = row.get(col_map.get("description", ""), "")
                qty = parse_float(row.get(col_map.get("quantity", ""), None))
                up = parse_float(row.get(col_map.get("unit_price", ""), None))
                lt = parse_float(row.get(col_map.get("line_total", ""), None))
                sku = row.get(col_map.get("sku", ""), "")

                if desc or qty or up:
                    line_items.append({
                        "description": str(desc),
                        "quantity": qty,
                        "unit_price": up,
                        "line_total": lt,
                        "sku": str(sku),
                    })

        low_conf = []
        if not invoice_number:
            low_conf.append("invoice_number")
        if not vendor_name:
            low_conf.append("vendor_name")
        if grand_total is None:
            low_conf.append("grand_total")

        conf = 1.0 - (len(low_conf) * 0.15)

        return {
            "invoice_number": str(invoice_number) if invoice_number else None,
            "vendor_name": str(vendor_name) if vendor_name else None,
            "vendor_id": str(vendor_id) if vendor_id else None,
            "po_number": str(po_number) if po_number else None,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "payment_terms": str(payment_terms) if payment_terms else None,
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "grand_total": grand_total,
            "line_items": line_items,
            "raw_text": df.to_csv(index=False),
            "source_file": str(path),
            "source_file_type": ftype,
            "_overall_confidence": max(0.0, conf),
            "_low_confidence_fields": low_conf,
        }
