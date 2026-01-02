"""
Financial data model for storing organisation-specific financial data
"""

from sqlalchemy import Column, String, Date, Numeric, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class FinancialData(Base):
    __tablename__ = "financial_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    period_date = Column(Date, nullable=False)
    period_type = Column(String(20), default="monthly")  # monthly, quarterly, yearly
    account_category = Column(String(100), nullable=False)  # Revenue, COGS, OpEx, etc.
    account_name = Column(String(255), nullable=False)
    actual_amount = Column(Numeric(15, 2), default=0)
    budget_amount = Column(Numeric(15, 2), default=0)
    prior_year_amount = Column(Numeric(15, 2), default=0)
    variance_percent = Column(Numeric(10, 4))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    organisation = relationship("Organisation", back_populates="financial_data")

    def __repr__(self):
        return f"<FinancialData {self.account_name} {self.period_date}>"

    @property
    def variance_amount(self):
        """Calculate variance between actual and budget"""
        return (self.actual_amount or 0) - (self.budget_amount or 0)


class DataUpload(Base):
    __tablename__ = "data_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # csv, xlsx
    file_size_bytes = Column(Integer)
    row_count = Column(Integer, default=0)
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    error_message = Column(Text)
    processing_started_at = Column(DateTime(timezone=True))
    processing_completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    organisation = relationship("Organisation", back_populates="uploads")
    uploader = relationship("User")

    def __repr__(self):
        return f"<DataUpload {self.filename} - {self.status}>"


class KPIMetric(Base):
    __tablename__ = "kpi_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False)
    metric_date = Column(Date, nullable=False)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Numeric(15, 4))
    metric_unit = Column(String(50))  # currency, percentage, number
    target_value = Column(Numeric(15, 4))
    prior_period_value = Column(Numeric(15, 4))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    organisation = relationship("Organisation", back_populates="kpi_metrics")

    def __repr__(self):
        return f"<KPIMetric {self.metric_name}: {self.metric_value}>"
