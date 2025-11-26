"""
FinSight AI - Data Source Model
===============================
SQLAlchemy models for data sources (CSV uploads, ERP connections).
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class DataSourceType(str, enum.Enum):
    """Types of data sources supported."""
    CSV = "csv"
    XERO = "xero"
    NETSUITE = "netsuite"
    QUICKBOOKS = "quickbooks"
    SAGE = "sage"
    MANUAL = "manual"


class ConnectionStatus(str, enum.Enum):
    """Data source connection status."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    PENDING = "pending"
    SYNCING = "syncing"


class DataSource(Base):
    """
    Data source model - represents a connection to financial data.
    
    Can be a CSV upload or an ERP integration (Xero, NetSuite, etc.)
    """
    __tablename__ = "data_sources"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Foreign key to organisation (multi-tenancy)
    organisation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Source details
    name = Column(String(255), nullable=False)  # e.g., "Main Xero Account"
    source_type = Column(String(50), nullable=False)  # csv, xero, netsuite, etc.
    
    # Connection status
    connection_status = Column(
        String(50),
        default=ConnectionStatus.PENDING.value,
        nullable=False
    )
    
    # OAuth credentials (encrypted in production)
    credentials = Column(JSON, nullable=True)  # OAuth tokens, API keys
    
    # Sync configuration
    sync_frequency = Column(String(50), default="daily")  # daily, weekly, manual
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String(50), nullable=True)
    last_sync_error = Column(Text, nullable=True)
    
    # For CSV sources
    file_path = Column(String(500), nullable=True)  # S3 path or similar
    original_filename = Column(String(255), nullable=True)
    
    # Metadata
    row_count = Column(String(50), nullable=True)  # Records imported
    date_range_start = Column(DateTime, nullable=True)
    date_range_end = Column(DateTime, nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organisation = relationship("Organisation", back_populates="data_sources")
    financial_records = relationship(
        "FinancialRecord",
        back_populates="data_source",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self):
        return f"<DataSource {self.name} ({self.source_type})>"


class FinancialRecord(Base):
    """
    Financial record model - stores actual financial data.
    
    Standardised schema for data from any source (CSV, Xero, NetSuite, etc.)
    """
    __tablename__ = "financial_records"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Foreign keys
    organisation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    data_source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Date dimension
    record_date = Column(DateTime, nullable=False, index=True)
    period_year = Column(String(4), nullable=True)  # e.g., "2025"
    period_month = Column(String(2), nullable=True)  # e.g., "01"
    period_quarter = Column(String(2), nullable=True)  # e.g., "Q1"
    
    # Account dimension
    account_code = Column(String(100), nullable=True, index=True)
    account_name = Column(String(255), nullable=True)
    account_category = Column(String(100), nullable=True)  # Revenue, COGS, OpEx, etc.
    account_subcategory = Column(String(100), nullable=True)
    
    # Department/Cost Centre dimension
    department_code = Column(String(100), nullable=True, index=True)
    department_name = Column(String(255), nullable=True)
    
    # Product dimension (optional)
    product_code = Column(String(100), nullable=True)
    product_name = Column(String(255), nullable=True)
    
    # Amounts
    amount_actual = Column(String(50), nullable=True)  # Stored as string, parsed as needed
    amount_budget = Column(String(50), nullable=True)
    amount_forecast = Column(String(50), nullable=True)
    amount_prior_year = Column(String(50), nullable=True)
    
    # Currency
    currency = Column(String(3), default="GBP")
    
    # Record type
    record_type = Column(String(50), default="actual")  # actual, budget, forecast
    
    # Source reference
    source_transaction_id = Column(String(255), nullable=True)  # Original ID from ERP
    
    # Flexible metadata
    metadata = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    data_source = relationship("DataSource", back_populates="financial_records")
    
    def __repr__(self):
        return f"<FinancialRecord {self.account_code} {self.record_date}>"
