"""
FinSight AI - Financial Data Router
===================================
API endpoints for financial data with tenant isolation.
"""

from typing import List, Optional
from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user, get_current_organisation_id, require_member
from app.models.user import User
from app.models.financial_data import DataUpload
from app.schemas.financial_data import (
    FinancialDataResponse,
    FinancialDataCreate,
    DashboardSummary,
    MonthlyTrend,
    CategoryBreakdown,
    UploadResponse,
    DataUploadStatus
)
from app.services.financial_data_service import FinancialDataService, CSVProcessor


router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    year: Optional[int] = Query(None, description="Year for summary (defaults to current year)"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id)
):
    """
    Get dashboard summary KPIs for the current organisation.
    All data is filtered to only show the authenticated user's organisation.
    """
    service = FinancialDataService(db, organisation_id)
    return await service.get_dashboard_summary(year)


@router.get("/trends", response_model=List[MonthlyTrend])
async def get_monthly_trends(
    category: str = Query("Revenue", description="Account category to trend"),
    year: Optional[int] = Query(None, description="Year for trends"),
    months: int = Query(12, ge=1, le=24, description="Number of months"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id)
):
    """
    Get monthly trend data for charts.
    """
    service = FinancialDataService(db, organisation_id)
    return await service.get_monthly_trends(category, year, months)


@router.get("/breakdown", response_model=List[CategoryBreakdown])
async def get_category_breakdown(
    year: Optional[int] = Query(None, description="Year for breakdown"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id)
):
    """
    Get breakdown by account category.
    """
    service = FinancialDataService(db, organisation_id)
    return await service.get_category_breakdown(year)


@router.get("/", response_model=List[FinancialDataResponse])
async def get_financial_data(
    start_date: Optional[date] = Query(None, description="Filter start date"),
    end_date: Optional[date] = Query(None, description="Filter end date"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(1000, ge=1, le=10000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id)
):
    """
    Get all financial data for the organisation with optional filters.
    """
    service = FinancialDataService(db, organisation_id)
    data = await service.get_all_data(start_date, end_date, category, limit)
    return data


@router.post("/", response_model=FinancialDataResponse, status_code=status.HTTP_201_CREATED)
async def create_financial_data(
    data: FinancialDataCreate,
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id),
    current_user: User = Depends(require_member)
):
    """
    Create a single financial data record.
    Requires member role or higher.
    """
    service = FinancialDataService(db, organisation_id)
    return await service.create_financial_data(data)


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(..., description="CSV file with financial data"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id),
    current_user: User = Depends(require_member)
):
    """
    Upload a CSV file with financial data.

    Required columns: period_date, account_category, account_name, actual_amount
    Optional columns: budget_amount, prior_year_amount, notes, period_type

    Data will be upserted (updated if exists, inserted if new).
    """
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are supported"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Create upload record
    upload = DataUpload(
        organisation_id=organisation_id,
        uploaded_by=current_user.id,
        filename=file.filename,
        file_type='csv',
        file_size_bytes=file_size,
        status='processing'
    )
    db.add(upload)
    await db.flush()

    try:
        # Parse CSV
        data_list = CSVProcessor.parse_csv(content)

        # Bulk upsert
        service = FinancialDataService(db, organisation_id)
        row_count = await service.bulk_upsert_financial_data(data_list)

        # Update upload record
        upload.status = 'completed'
        upload.row_count = row_count
        await db.commit()

        return UploadResponse(
            id=upload.id,
            filename=file.filename,
            status='completed',
            row_count=row_count,
            message=f"Successfully processed {row_count} records"
        )

    except ValueError as e:
        upload.status = 'failed'
        upload.error_message = str(e)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        upload.status = 'failed'
        upload.error_message = str(e)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}"
        )


@router.get("/uploads", response_model=List[DataUploadStatus])
async def get_upload_history(
    limit: int = Query(20, ge=1, le=100, description="Max uploads to return"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id),
    current_user: User = Depends(get_current_user)
):
    """
    Get upload history for the organisation.
    """
    from sqlalchemy import select

    result = await db.execute(
        select(DataUpload)
        .where(DataUpload.organisation_id == organisation_id)
        .order_by(DataUpload.created_at.desc())
        .limit(limit)
    )
    uploads = result.scalars().all()
    return uploads


@router.get("/template")
async def download_csv_template():
    """
    Download a CSV template for financial data uploads.
    """
    template = CSVProcessor.generate_template()

    return StreamingResponse(
        iter([template]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=finsight_data_template.csv"
        }
    )


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_data(
    confirm: bool = Query(False, description="Must be true to confirm deletion"),
    db: AsyncSession = Depends(get_db),
    organisation_id: UUID = Depends(get_current_organisation_id),
    current_user: User = Depends(require_member)
):
    """
    Delete all financial data for the organisation.
    Requires confirmation parameter and owner role.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to delete all data"
        )

    # Only owners can delete all data
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organisation owners can delete all data"
        )

    service = FinancialDataService(db, organisation_id)
    await service.delete_all_data()

    return None
