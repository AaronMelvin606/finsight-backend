"""
FinSight AI - Financial Data Schemas
====================================
Pydantic models for financial data request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID
from decimal import Decimal


class FinancialDataBase(BaseModel):
    """Base schema for financial data."""
    period_date: date
    period_type: str = "monthly"
    account_category: str
    account_name: str
    actual_amount: Decimal = Field(default=Decimal("0"))
    budget_amount: Decimal = Field(default=Decimal("0"))
    prior_year_amount: Decimal = Field(default=Decimal("0"))
    notes: Optional[str] = None


class FinancialDataCreate(FinancialDataBase):
    """Schema for creating financial data."""
    pass


class FinancialDataUpdate(BaseModel):
    """Schema for updating financial data."""
    actual_amount: Optional[Decimal] = None
    budget_amount: Optional[Decimal] = None
    prior_year_amount: Optional[Decimal] = None
    notes: Optional[str] = None


class FinancialDataResponse(FinancialDataBase):
    """Schema for financial data response."""
    id: UUID
    organisation_id: UUID
    variance_amount: Optional[Decimal] = None
    variance_percent: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FinancialDataBulkCreate(BaseModel):
    """Schema for bulk creating financial data (CSV upload processing)."""
    data: List[FinancialDataCreate]


class UploadResponse(BaseModel):
    """Schema for file upload response."""
    id: UUID
    filename: str
    status: str
    row_count: int
    message: str


class DataUploadStatus(BaseModel):
    """Schema for data upload status."""
    id: UUID
    filename: str
    file_type: str
    status: str
    row_count: int
    error_message: Optional[str] = None
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    """Summary data for dashboard."""
    organisation_id: UUID
    organisation_name: str
    period: str

    # KPIs
    revenue_ytd: Decimal = Field(default=Decimal("0"))
    revenue_budget: Decimal = Field(default=Decimal("0"))
    revenue_variance_percent: Optional[Decimal] = None

    gross_margin_percent: Optional[Decimal] = None
    gross_margin_budget_percent: Optional[Decimal] = None

    ebitda: Decimal = Field(default=Decimal("0"))
    ebitda_budget: Decimal = Field(default=Decimal("0"))

    opex_actual: Decimal = Field(default=Decimal("0"))
    opex_budget: Decimal = Field(default=Decimal("0"))

    # Metadata
    last_updated: Optional[datetime] = None
    data_through_date: Optional[date] = None


class MonthlyTrend(BaseModel):
    """Monthly trend data point."""
    period: str
    actual: Decimal
    budget: Decimal
    prior_year: Optional[Decimal] = None


class CategoryBreakdown(BaseModel):
    """Category breakdown for charts."""
    category: str
    actual: Decimal
    budget: Decimal
    variance: Decimal
    variance_percent: Optional[Decimal] = None


class KPIMetricBase(BaseModel):
    """Base schema for KPI metrics."""
    metric_date: date
    metric_name: str
    metric_value: Optional[Decimal] = None
    metric_unit: Optional[str] = None
    target_value: Optional[Decimal] = None
    prior_period_value: Optional[Decimal] = None


class KPIMetricCreate(KPIMetricBase):
    """Schema for creating KPI metric."""
    pass


class KPIMetricResponse(KPIMetricBase):
    """Schema for KPI metric response."""
    id: UUID
    organisation_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class KPIDashboard(BaseModel):
    """KPI dashboard data."""
    organisation_id: UUID
    organisation_name: str
    metrics: List[KPIMetricResponse]
    trends: List[MonthlyTrend]
    category_breakdown: List[CategoryBreakdown]
