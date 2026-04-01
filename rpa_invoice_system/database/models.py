"""SQLAlchemy ORM models for the RPA invoice system."""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class InvoiceStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    AUTO_APPROVED = "auto_approved"
    FLAGGED = "flagged"
    HUMAN_APPROVED = "human_approved"
    REJECTED = "rejected"
    FAILED = "failed"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identification
    invoice_number = Column(String(100), nullable=True, index=True)
    vendor_name = Column(String(255), nullable=True)
    vendor_id = Column(String(100), nullable=True)
    po_number = Column(String(100), nullable=True)

    # Dates
    invoice_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    payment_terms = Column(String(100), nullable=True)

    # Amounts
    subtotal = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    grand_total = Column(Float, nullable=True)

    # File info
    source_file = Column(String(500), nullable=False)
    source_file_type = Column(String(20), nullable=True)
    file_hash = Column(String(64), nullable=True)

    # Processing
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.PENDING, index=True)
    confidence_score = Column(Float, nullable=True)
    low_confidence_fields = Column(JSON, nullable=True)   # list of field names
    validation_errors = Column(JSON, nullable=True)        # list of error dicts
    validation_warnings = Column(JSON, nullable=True)

    # Timestamps
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approved_by = Column(String(100), nullable=True)

    # Raw extracted text (for debugging / re-extraction)
    raw_text = Column(Text, nullable=True)

    # Relationships
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="invoice", cascade="all, delete-orphan")
    corrections = relationship("CorrectionHistory", back_populates="invoice", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_number": self.invoice_number,
            "vendor_name": self.vendor_name,
            "vendor_id": self.vendor_id,
            "po_number": self.po_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "payment_terms": self.payment_terms,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "grand_total": self.grand_total,
            "source_file": self.source_file,
            "status": self.status.value if self.status else None,
            "confidence_score": self.confidence_score,
            "low_confidence_fields": self.low_confidence_fields,
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "approved_by": self.approved_by,
        }


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)

    line_number = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    line_total = Column(Float, nullable=True)
    sku = Column(String(100), nullable=True)

    invoice = relationship("Invoice", back_populates="line_items")

    def to_dict(self):
        return {
            "id": self.id,
            "line_number": self.line_number,
            "description": self.description,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "sku": self.sku,
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"
    # Immutable audit trail — never update rows, only insert
    __table_args__ = {"comment": "Immutable audit trail"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)

    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    action = Column(String(100), nullable=False)   # e.g. RECEIVED, EXTRACTED, VALIDATED, APPROVED
    actor = Column(String(100), default="system")  # system or user name
    detail = Column(Text, nullable=True)
    result = Column(String(50), nullable=True)      # SUCCESS / FAILURE / WARNING

    invoice = relationship("Invoice", back_populates="audit_logs")


class CorrectionHistory(Base):
    __tablename__ = "correction_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)

    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    corrected_by = Column(String(100), nullable=False)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    note = Column(Text, nullable=True)

    invoice = relationship("Invoice", back_populates="corrections")
