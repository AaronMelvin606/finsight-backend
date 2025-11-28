# ============================================
# FINSIGHT AI - DATA SOURCE MODELS
# ============================================

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, Boolean, Numeric, Enum, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class DataSourceType(str, enum.Enum):
    """Supported data source types."""
    CSV = "csv"
    XERO = "xero"
    NETSUITE = "netsuite"
    QUICKBOOKS = "quickbooks"
    SAGE = "sage"
    API = "api"


class ConnectionStatus(str, enum.Enum):
    """Data source connection status."""
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class DataSource(Base):
    """
    Data source connections for each organisation.
    Stores ERP/accounting system connection details.
    """
    __tablename__ = "data_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Relationship to organisation
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    
    # Source details
    name = Column(String(255), nullable=False)
    source_type = Column(Enum(DataSourceType), nullable=False)
    description = Column(Text, nullable=True)
    
    # Connection details (encrypted in production)
    connection_config = Column(JSON, nullable=True)  # Stores API keys, tokens, etc.
    
    # Status tracking
    status = Column(Enum(ConnectionStatus), default=ConnectionStatus.PENDING)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    
    # Record counts
    records_synced = Column(Integer, default=0)
    
    # Audit fields
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organisation = relationship("Organisation", back_populates="data_sources")
    financial_records = relationship("FinancialRecord", back_populates="data_source", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DataSource {self.name} ({self.source_type})>"


class FinancialRecord(Base):
    """
    Standardised financial records from various data sources.
    This is the unified schema for all financial data.
    """
    __tablename__ = "financial_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Relationships
    data_source_id = Column(UUID(as_uuid=True), ForeignKey("data_sources.id"), nullable=False)
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    
    # Record identification
    external_id = Column(String(255), nullable=True)  # ID from source system
    record_type = Column(String(50), nullable=False)  # e.g., "journal", "invoice", "payment"
    
    # Date fields
    record_date = Column(DateTime, nullable=False)
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    
    # Account structure
    account_code = Column(String(50), nullable=False)
    account_name = Column(String(255), nullable=True)
    account_category = Column(String(100), nullable=True)  # e.g., "Revenue", "COGS", "OpEx"
    
    # Department/Cost Centre
    department_code = Column(String(50), nullable=True)
    department_name = Column(String(255), nullable=True)
    
    # Financial amounts
    amount_actual = Column(Numeric(15, 2), nullable=True)
    amount_budget = Column(Numeric(15, 2), nullable=True)
    amount_forecast = Column(Numeric(15, 2), nullable=True)
    amount_prior_year = Column(Numeric(15, 2), nullable=True)
    
    # Currency
    currency = Column(String(3), default="GBP")
    exchange_rate = Column(Numeric(10, 6), default=1.0)
    
    # Additional dimensions
    project_code = Column(String(50), nullable=True)
    customer_code = Column(String(50), nullable=True)
    vendor_code = Column(String(50), nullable=True)
    
    # Description and notes
    description = Column(Text, nullable=True)
    source_reference = Column(String(255), nullable=True)  # Original doc reference
    
    # Extra data from source (flexible JSON)
    extra_data = Column(JSON, nullable=True)
    
    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    data_source = relationship("DataSource", back_populates="financial_records")
    organisation = relationship("Organisation", back_populates="financial_records")

    def __repr__(self):
        return f"<FinancialRecord {self.account_code} {self.record_date} {self.amount_actual}>"
