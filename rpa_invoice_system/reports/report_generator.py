"""
Daily summary report generator — produces both a PDF and a CSV export.
"""
import csv
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List

from config import config

logger = logging.getLogger(__name__)


class DailySummaryReport:
    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or (config.BASE_DIR / "reports" / "output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, stats: dict, invoices: list, target_date: date = None) -> dict:
        """
        Generate PDF report + CSV export.
        Returns dict with keys: pdf_path, csv_path.
        """
        if target_date is None:
            target_date = date.today()

        pdf_path = self._generate_pdf(stats, target_date)
        csv_path = self._export_csv(invoices, target_date)

        return {"pdf_path": str(pdf_path), "csv_path": str(csv_path)}

    # ── PDF ──────────────────────────────────────────────────────────────────

    def _generate_pdf(self, stats: dict, target_date: date) -> Path:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
            )
        except ImportError:
            logger.warning("reportlab not installed — skipping PDF generation.")
            return Path("/dev/null")

        filename = self.output_dir / f"invoice_report_{target_date.isoformat()}.pdf"
        doc = SimpleDocTemplate(str(filename), pagesize=letter,
                                topMargin=0.75 * inch, bottomMargin=0.75 * inch)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=18, spaceAfter=6)
        h2_style = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceAfter=4)
        normal = styles["Normal"]

        story = []
        story.append(Paragraph("RPA Invoice Processing — Daily Summary", title_style))
        story.append(Paragraph(f"Report Date: {target_date.strftime('%B %d, %Y')}", normal))
        story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", normal))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
        story.append(Spacer(1, 0.2 * inch))

        # Overview table
        story.append(Paragraph("Processing Overview", h2_style))
        overview_data = [
            ["Metric", "Count"],
            ["Total Invoices Received", stats.get("total", 0)],
            ["Auto-Approved", stats.get("auto_approved", 0)],
            ["Flagged for Human Review", stats.get("flagged", 0)],
            ["Human Approved", stats.get("human_approved", 0)],
            ["Rejected", stats.get("rejected", 0)],
        ]
        t = Table(overview_data, colWidths=[4 * inch, 2 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2 * inch))

        # Error breakdown
        error_counts = stats.get("error_type_counts", {})
        if error_counts:
            story.append(Paragraph("Error Types Detected", h2_style))
            err_data = [["Error Type", "Occurrences"]] + [
                [k, v] for k, v in sorted(error_counts.items(), key=lambda x: -x[1])
            ]
            et = Table(err_data, colWidths=[4 * inch, 2 * inch])
            et.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e74c3c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fdf3f3")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(et)
            story.append(Spacer(1, 0.2 * inch))

        # Vendor breakdown
        vendor_counts = stats.get("vendor_breakdown", {})
        if vendor_counts:
            story.append(Paragraph("Vendor Invoice Counts", h2_style))
            vd_data = [["Vendor", "Invoices"]] + [
                [k, v] for k, v in sorted(vendor_counts.items(), key=lambda x: -x[1])[:15]
            ]
            vt = Table(vd_data, colWidths=[4 * inch, 2 * inch])
            vt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdf4")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(vt)

        doc.build(story)
        logger.info("PDF report saved: %s", filename)
        return filename

    # ── CSV export ────────────────────────────────────────────────────────────

    def _export_csv(self, invoices: list, target_date: date) -> Path:
        filename = self.output_dir / f"invoices_export_{target_date.isoformat()}.csv"

        fieldnames = [
            "id", "invoice_number", "vendor_name", "vendor_id", "po_number",
            "invoice_date", "due_date", "payment_terms",
            "subtotal", "tax_amount", "grand_total",
            "status", "confidence_score", "source_file",
            "received_at", "processed_at", "approved_by",
        ]

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for inv in invoices:
                row = inv if isinstance(inv, dict) else inv.to_dict()
                writer.writerow(row)

        logger.info("CSV export saved: %s", filename)
        return filename
