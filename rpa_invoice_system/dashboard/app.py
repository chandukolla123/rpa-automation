"""Flask dashboard for reviewing flagged invoices."""
import json
import logging
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from config import config
from database.connection import SessionLocal, init_db
from database.models import InvoiceStatus
from database.queries import (
    add_audit_log, get_all_invoices, get_daily_stats,
    get_invoice, get_invoices_by_status, update_invoice_fields, update_invoice_status,
)
from reports.report_generator import DailySummaryReport

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = config.SECRET_KEY

    init_db()

    # ── Index ─────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        db = SessionLocal()
        try:
            flagged = get_invoices_by_status(db, InvoiceStatus.FLAGGED)
            pending = get_invoices_by_status(db, InvoiceStatus.PENDING)
            processing = get_invoices_by_status(db, InvoiceStatus.PROCESSING)
            recent = get_all_invoices(db, limit=50)
            stats = get_daily_stats(db, date.today())
        finally:
            db.close()

        return render_template(
            "index.html",
            flagged=flagged,
            pending=pending,
            processing=processing,
            recent=recent,
            stats=stats,
        )

    # ── Review single invoice ─────────────────────────────────────────────────

    @app.route("/invoice/<int:invoice_id>")
    def review_invoice(invoice_id: int):
        db = SessionLocal()
        try:
            invoice = get_invoice(db, invoice_id)
            if not invoice:
                return "Invoice not found", 404

            # Try to serve the original file as a preview
            src = Path(invoice.source_file)
            preview_url = None
            if src.exists() and src.suffix.lower() in (".jpg", ".jpeg", ".png"):
                preview_url = f"/preview/{invoice_id}"

        finally:
            db.close()

        return render_template(
            "review.html",
            invoice=invoice,
            preview_url=preview_url,
            line_items=invoice.line_items,
            audit_logs=invoice.audit_logs,
            corrections=invoice.corrections,
        )

    # ── Approve / Reject ──────────────────────────────────────────────────────

    @app.route("/invoice/<int:invoice_id>/approve", methods=["POST"])
    def approve_invoice(invoice_id: int):
        actor = request.form.get("actor", "reviewer")
        db = SessionLocal()
        try:
            update_invoice_status(db, invoice_id, InvoiceStatus.HUMAN_APPROVED, actor)
            add_audit_log(db, invoice_id, "HUMAN_APPROVED", f"Approved by {actor}", "SUCCESS", actor)
            db.commit()
        finally:
            db.close()
        return redirect(url_for("index"))

    @app.route("/invoice/<int:invoice_id>/reject", methods=["POST"])
    def reject_invoice(invoice_id: int):
        actor = request.form.get("actor", "reviewer")
        reason = request.form.get("reason", "")
        db = SessionLocal()
        try:
            update_invoice_status(db, invoice_id, InvoiceStatus.REJECTED, actor)
            add_audit_log(db, invoice_id, "REJECTED", f"Rejected by {actor}: {reason}", "FAILURE", actor)
            db.commit()
        finally:
            db.close()
        return redirect(url_for("index"))

    # ── Field correction ──────────────────────────────────────────────────────

    @app.route("/invoice/<int:invoice_id>/correct", methods=["POST"])
    def correct_invoice(invoice_id: int):
        actor = request.form.get("actor", "reviewer")
        fields = {k: v for k, v in request.form.items()
                  if k not in ("actor", "csrf_token") and v.strip()}

        db = SessionLocal()
        try:
            update_invoice_fields(db, invoice_id, fields, actor)
            add_audit_log(
                db, invoice_id, "FIELD_CORRECTED",
                f"Fields updated by {actor}: {list(fields.keys())}",
                "SUCCESS", actor,
            )
            db.commit()
        finally:
            db.close()
        return redirect(url_for("review_invoice", invoice_id=invoice_id))

    # ── API endpoints ─────────────────────────────────────────────────────────

    @app.route("/api/invoices")
    def api_invoices():
        status_filter = request.args.get("status")
        db = SessionLocal()
        try:
            if status_filter:
                try:
                    s = InvoiceStatus(status_filter)
                    invoices = get_invoices_by_status(db, s)
                except ValueError:
                    return jsonify({"error": "Invalid status"}), 400
            else:
                invoices = get_all_invoices(db, limit=100)
            return jsonify([i.to_dict() for i in invoices])
        finally:
            db.close()

    @app.route("/api/stats")
    def api_stats():
        date_str = request.args.get("date", date.today().isoformat())
        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            return jsonify({"error": "Invalid date"}), 400
        db = SessionLocal()
        try:
            return jsonify(get_daily_stats(db, target))
        finally:
            db.close()

    @app.route("/api/invoice/<int:invoice_id>")
    def api_invoice(invoice_id: int):
        db = SessionLocal()
        try:
            inv = get_invoice(db, invoice_id)
            if not inv:
                return jsonify({"error": "Not found"}), 404
            data = inv.to_dict()
            data["line_items"] = [li.to_dict() for li in inv.line_items]
            data["audit_logs"] = [
                {"action": a.action, "actor": a.actor, "timestamp": a.timestamp.isoformat(),
                 "detail": a.detail, "result": a.result}
                for a in inv.audit_logs
            ]
            return jsonify(data)
        finally:
            db.close()

    # ── Daily report trigger ──────────────────────────────────────────────────

    @app.route("/report/generate", methods=["POST"])
    def generate_report():
        date_str = request.form.get("date", date.today().isoformat())
        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            return jsonify({"error": "Invalid date"}), 400

        db = SessionLocal()
        try:
            stats = get_daily_stats(db, target)
            invoices = get_all_invoices(db, limit=500)
            reporter = DailySummaryReport()
            paths = reporter.generate(stats, [i.to_dict() for i in invoices], target)
        finally:
            db.close()

        return jsonify({"success": True, **paths})

    return app
