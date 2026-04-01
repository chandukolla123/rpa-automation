"""
RPA Invoice Processing System — Entry Point

Usage:
    python main.py                  # Start watcher + dashboard
    python main.py --process FILE   # Process a single file and exit
    python main.py --report         # Generate today's report and exit
    python main.py --demo           # Load sample data and exit
"""
import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from config import config
from database.connection import init_db


def setup_logging():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.LOG_DIR / "rpa_system.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=fmt,
        handlers=handlers,
    )
    # Quieten noisy libraries
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


def run_watcher_thread(watcher):
    """Blocking loop — processes queue items as they arrive."""
    from pipeline import process_invoice

    watcher.start()
    logger.info("Watching inbox: %s", config.INBOX_DIR)

    while watcher._observer.is_alive():
        try:
            item = watcher.queue.get(timeout=1)
        except Exception:
            continue

        file_path: Path = item["path"]
        file_hash: str = item.get("file_hash", "")

        logger.info("Dequeued: %s", file_path.name)
        try:
            invoice_id = process_invoice(file_path, file_hash)
            if invoice_id:
                watcher.move_to_processed(file_path)
            else:
                watcher.move_to_failed(file_path)
        except Exception as exc:
            logger.error("Pipeline error for %s: %s", file_path.name, exc, exc_info=True)
            watcher.move_to_failed(file_path)
        finally:
            watcher.queue.task_done()


def run_email_poller(stop_event: threading.Event):
    """Periodically polls IMAP for new invoice emails."""
    import time
    from ingestion.email_reader import IMAPInvoiceReader

    reader = IMAPInvoiceReader()
    while not stop_event.is_set():
        try:
            count = reader.poll()
            if count:
                logger.info("Email poller: saved %d attachments.", count)
        except Exception as exc:
            logger.warning("Email poll error: %s", exc)
        stop_event.wait(config.IMAP_POLL_INTERVAL)


def run_flask(app):
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT,
            debug=config.FLASK_DEBUG, use_reloader=False)


def cmd_process_file(file_path: str):
    from pipeline import process_invoice
    path = Path(file_path)
    if not path.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)
    invoice_id = process_invoice(path)
    if invoice_id:
        print(f"SUCCESS: Invoice processed, ID={invoice_id}")
    else:
        print("FAILED: See logs for details.")


def cmd_generate_report():
    from datetime import date
    from database.connection import SessionLocal
    from database.queries import get_all_invoices, get_daily_stats
    from reports.report_generator import DailySummaryReport

    today = date.today()
    db = SessionLocal()
    try:
        stats = get_daily_stats(db, today)
        invoices = get_all_invoices(db, limit=500)
        reporter = DailySummaryReport()
        paths = reporter.generate(stats, [i.to_dict() for i in invoices], today)
    finally:
        db.close()

    print(f"PDF: {paths['pdf_path']}")
    print(f"CSV: {paths['csv_path']}")


def cmd_load_demo():
    """Copy sample invoices into the inbox so the pipeline processes them."""
    import shutil
    sample_dir = config.BASE_DIR / "sample_data"
    count = 0
    for f in sample_dir.glob("invoice_*.csv"):
        dest = config.INBOX_DIR / f.name
        shutil.copy2(f, dest)
        count += 1
        logger.info("Copied sample: %s", f.name)
    print(f"Loaded {count} sample invoices into {config.INBOX_DIR}")


def main():
    parser = argparse.ArgumentParser(description="RPA Invoice Processing System")
    parser.add_argument("--process", metavar="FILE", help="Process a single file and exit")
    parser.add_argument("--report", action="store_true", help="Generate today's report and exit")
    parser.add_argument("--demo", action="store_true", help="Load sample invoices into inbox and exit")
    args = parser.parse_args()

    setup_logging()
    init_db()
    logger.info("RPA Invoice System starting (env=%s).", config.APP_ENV)

    if args.process:
        cmd_process_file(args.process)
        return

    if args.report:
        cmd_generate_report()
        return

    if args.demo:
        cmd_load_demo()
        return

    # ── Full run: watcher + email poller + Flask ──────────────────────────────
    from ingestion.file_watcher import InvoiceFileWatcher
    from dashboard.app import create_app

    stop_event = threading.Event()
    watcher = InvoiceFileWatcher()

    # Watcher thread
    watcher_thread = threading.Thread(target=run_watcher_thread, args=(watcher,), daemon=True, name="watcher")
    watcher_thread.start()

    # Email poller thread (no-op if IMAP not configured)
    email_thread = threading.Thread(target=run_email_poller, args=(stop_event,), daemon=True, name="email-poller")
    email_thread.start()

    # Flask dashboard
    app = create_app()
    flask_thread = threading.Thread(target=run_flask, args=(app,), daemon=True, name="flask")
    flask_thread.start()

    logger.info("Dashboard running at http://%s:%d", config.FLASK_HOST, config.FLASK_PORT)
    logger.info("Press Ctrl+C to stop.")

    def _shutdown(sig, frame):
        logger.info("Shutting down...")
        stop_event.set()
        watcher.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Keep main thread alive
    flask_thread.join()


if __name__ == "__main__":
    main()
