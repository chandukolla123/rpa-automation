"""Central configuration loaded from .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


class Config:
    BASE_DIR: Path = BASE_DIR

    # App
    APP_ENV: str = os.getenv("APP_ENV", "development")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Storage
    INBOX_DIR: Path = BASE_DIR / os.getenv("INBOX_DIR", "storage/inbox")
    PROCESSED_DIR: Path = BASE_DIR / os.getenv("PROCESSED_DIR", "storage/processed")
    FAILED_DIR: Path = BASE_DIR / os.getenv("FAILED_DIR", "storage/failed")
    LOG_DIR: Path = BASE_DIR / os.getenv("LOG_DIR", "logs")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/rpa_invoices.db")

    # Reference data
    VENDORS_CSV: Path = BASE_DIR / os.getenv("VENDORS_CSV", "sample_data/vendors.csv")
    PURCHASE_ORDERS_CSV: Path = BASE_DIR / os.getenv("PURCHASE_ORDERS_CSV", "sample_data/purchase_orders.csv")

    # Validation
    AMOUNT_THRESHOLD: float = float(os.getenv("AMOUNT_THRESHOLD", "10000.00"))
    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))

    # Email
    IMAP_HOST: str = os.getenv("IMAP_HOST", "")
    IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))
    IMAP_USER: str = os.getenv("IMAP_USER", "")
    IMAP_PASSWORD: str = os.getenv("IMAP_PASSWORD", "")
    IMAP_FOLDER: str = os.getenv("IMAP_FOLDER", "INBOX")
    IMAP_POLL_INTERVAL: int = int(os.getenv("IMAP_POLL_INTERVAL_SECONDS", "60"))

    # Flask
    FLASK_HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Tesseract
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")

    SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".csv", ".xlsx", ".xls"}

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.INBOX_DIR, cls.PROCESSED_DIR, cls.FAILED_DIR, cls.LOG_DIR]:
            d.mkdir(parents=True, exist_ok=True)


config = Config()
config.ensure_dirs()
