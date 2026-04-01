# RPA Invoice Processing System

An end-to-end Robotic Process Automation pipeline that ingests, extracts, validates,
stores, and reviews invoices — targeting ~200 invoices/day with zero manual data entry.

---

## Architecture Overview

```
storage/inbox/          ← Drop files here (or configure email)
       │
       ▼
 InvoiceFileWatcher     ← Watchdog + sweep on startup
       │
       ▼
 InvoiceExtractor       ← pdfplumber / pytesseract / pandas
       │                   → structured field dict
       ▼
 InvoiceValidator       ← Math · Dates · Vendor · PO · Duplicate · Threshold
       │
       ├── PASS → AUTO_APPROVED → SQLite DB
       │
       └── FAIL → FLAGGED → SQLite DB → Flask Dashboard (http://localhost:5000)
                                              │
                                   Human reviews, corrects, approves/rejects
                                              │
                                        AuditLog (immutable)
```

---

## Quick Start

### 1. Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| Tesseract OCR | 5.x (only needed for image/scanned PDFs) |
| poppler | latest (only needed for PDF→image fallback) |

**Install Tesseract (Windows):**
Download from https://github.com/UB-Mannheim/tesseract/wiki
Then set `TESSERACT_CMD` in your `.env`.

### 2. Install Dependencies

```bash
cd rpa_invoice_system
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env — at minimum review TESSERACT_CMD if using OCR
```

### 4. Run

```bash
# Full system: file watcher + dashboard
python main.py

# Dashboard: http://localhost:5000
```

---

## Usage Modes

```bash
# Process a single file immediately
python main.py --process path/to/invoice.pdf

# Load all 5 sample invoices into the inbox for demo
python main.py --demo

# Generate today's PDF + CSV report
python main.py --report
```

---

## Supported Invoice Formats

| Format | Method |
|--------|--------|
| `.pdf` | pdfplumber (text) → OCR fallback |
| `.jpg` / `.png` | pytesseract OCR |
| `.csv` | pandas structured parser |
| `.xlsx` / `.xls` | pandas structured parser |

---

## Project Structure

```
rpa_invoice_system/
├── main.py                  # Entry point
├── config.py                # All settings (reads .env)
├── pipeline.py              # Extract → Validate → Persist flow
│
├── ingestion/
│   ├── file_watcher.py      # Watchdog + file queue
│   └── email_reader.py      # IMAP attachment downloader
│
├── extraction/
│   ├── extractor.py         # Dispatch by file type
│   └── field_parser.py      # Regex + heuristic field parsers
│
├── validation/
│   └── validator.py         # All business rules
│
├── database/
│   ├── models.py            # SQLAlchemy ORM (Invoice, LineItem, AuditLog, ...)
│   ├── connection.py        # Engine + session factory
│   └── queries.py           # Reusable query helpers
│
├── dashboard/
│   ├── app.py               # Flask application
│   └── templates/           # Jinja2 HTML templates
│
├── reports/
│   └── report_generator.py  # PDF (reportlab) + CSV exports
│
├── tests/                   # pytest suite
├── sample_data/             # 5 test invoices + vendors.csv + purchase_orders.csv
├── storage/
│   ├── inbox/               # Drop new invoices here
│   ├── processed/           # Successfully processed (never deleted)
│   └── failed/              # Extraction failures
└── logs/
    └── rpa_system.log
```

---

## Reference Data Files

### `sample_data/vendors.csv`
Master vendor list used to verify invoice vendors.

| Column | Description |
|--------|-------------|
| `vendor_id` | Unique vendor code (e.g. V001) |
| `vendor_name` | Full vendor name (fuzzy-matched) |
| `payment_terms` | Expected terms |
| `active` | true/false |

### `sample_data/purchase_orders.csv`
Open PO list for cross-referencing invoice PO numbers.

| Column | Description |
|--------|-------------|
| `po_number` | PO identifier (e.g. PO-2024-001) |
| `vendor_id` | Linked vendor |
| `status` | `open` / `closed` / `cancelled` |
| `amount` | Approved PO amount |

---

## Validation Rules

| Rule | Error Type | Blocking? |
|------|-----------|-----------|
| Required fields present | `MISSING_FIELD` | Yes |
| Line qty × price = line total | `LINE_ITEM_MATH` | Yes |
| Sum of lines = subtotal | `SUBTOTAL_MISMATCH` | Yes |
| Subtotal + tax = grand total | `GRAND_TOTAL_MISMATCH` | Yes |
| Invoice date not in future | `FUTURE_INVOICE_DATE` | Yes |
| Due date after invoice date | `DUE_BEFORE_INVOICE` | Yes |
| Vendor in master list | `UNKNOWN_VENDOR` | Yes |
| PO number in open POs | `PO_NOT_FOUND` / `PO_CLOSED` | Yes |
| Duplicate invoice | `DUPLICATE_INVOICE` | Yes |
| Amount > $10,000 | `HIGH_VALUE` | Warning (flags for review) |
| Low OCR confidence | `LOW_CONFIDENCE` | Warning |
| Missing PO number | `MISSING_PO` | Warning |

---

## Dashboard

`http://localhost:5000`

- **Index**: KPI cards + flagged queue + recent invoices table
- **Review page**: side-by-side errors/warnings + editable fields + approve/reject
- **Audit trail**: every action is logged immutably per invoice
- **Correction history**: tracks every field change with old/new value + actor

### REST API

```
GET  /api/invoices?status=flagged    # List invoices (filter by status)
GET  /api/invoice/<id>               # Full invoice detail with line items + audit log
GET  /api/stats?date=2024-03-01      # Daily statistics
POST /report/generate                # Trigger PDF + CSV report generation
```

---

## Sample Invoices

| File | Scenario | Expected Result |
|------|----------|----------------|
| `invoice_01_clean.csv` | Perfect invoice | AUTO_APPROVED |
| `invoice_02_math_error.csv` | Grand total mismatch | FLAGGED (GRAND_TOTAL_MISMATCH) |
| `invoice_03_duplicate.csv` | Same as #01 resent | FLAGGED (DUPLICATE_INVOICE) |
| `invoice_04_missing_po.csv` | No PO number | FLAGGED (MISSING_PO warning) |
| `invoice_05_high_value.csv` | $15,120 invoice | FLAGGED (HIGH_VALUE) |

Run the demo:
```bash
python main.py --demo   # copies samples to inbox
python main.py          # starts processing + dashboard
```

---

## Running Tests

```bash
cd rpa_invoice_system
pytest tests/ -v --tb=short
```

---

## Email Ingestion (Optional)

Set in `.env`:
```
IMAP_HOST=imap.gmail.com
IMAP_USER=invoices@yourcompany.com
IMAP_PASSWORD=your-app-password
IMAP_POLL_INTERVAL_SECONDS=60
```

The system polls the mailbox every 60 seconds, downloads PDF/image/Excel attachments,
saves them to `storage/inbox/`, and they are auto-picked up by the file watcher.

---

## Configuration Reference (`.env`)

| Key | Default | Description |
|-----|---------|-------------|
| `INBOX_DIR` | `storage/inbox` | Folder to watch |
| `AMOUNT_THRESHOLD` | `10000.00` | Flag invoices above this |
| `CONFIDENCE_THRESHOLD` | `0.75` | OCR confidence below this flags invoice |
| `DATABASE_URL` | `sqlite:///rpa_invoices.db` | Any SQLAlchemy URL |
| `TESSERACT_CMD` | `tesseract` | Path to tesseract binary |
| `FLASK_PORT` | `5000` | Dashboard port |
