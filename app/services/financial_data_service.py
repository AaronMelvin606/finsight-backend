"""
FinSight AI - Financial Data Service
====================================
Service for managing financial data with tenant isolation.
"""

from typing import List, Optional
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
import csv
import io

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, delete
from sqlalchemy.dialects.postgresql import insert

from app.models.financial_data import FinancialData, DataUpload, KPIMetric
from app.schemas.financial_data import (
    FinancialDataCreate,
    DashboardSummary,
    MonthlyTrend,
    CategoryBreakdown
)


class FinancialDataService:
    """Service for managing financial data with tenant isolation."""

    def __init__(self, db: AsyncSession, organisation_id: UUID):
        self.db = db
        self.organisation_id = organisation_id

    async def get_all_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        category: Optional[str] = None,
        limit: int = 1000
    ) -> List[FinancialData]:
        """Get financial data for the organisation with optional filters."""

        query = select(FinancialData).where(
            FinancialData.organisation_id == self.organisation_id
        )

        if start_date:
            query = query.where(FinancialData.period_date >= start_date)
        if end_date:
            query = query.where(FinancialData.period_date <= end_date)
        if category:
            query = query.where(FinancialData.account_category == category)

        query = query.order_by(FinancialData.period_date.desc()).limit(limit)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_dashboard_summary(self, year: int = None) -> DashboardSummary:
        """Get dashboard summary KPIs for the organisation."""

        if year is None:
            year = datetime.now().year

        # Get organisation name
        from app.models.organisation import Organisation
        org_result = await self.db.execute(
            select(Organisation).where(Organisation.id == self.organisation_id)
        )
        org = org_result.scalar_one_or_none()
        org_name = org.name if org else "Unknown"

        # Calculate YTD Revenue
        revenue_query = select(
            func.sum(FinancialData.actual_amount).label('actual'),
            func.sum(FinancialData.budget_amount).label('budget'),
            func.sum(FinancialData.prior_year_amount).label('prior_year')
        ).where(
            and_(
                FinancialData.organisation_id == self.organisation_id,
                FinancialData.account_category == 'Revenue',
                func.extract('year', FinancialData.period_date) == year
            )
        )
        revenue_result = await self.db.execute(revenue_query)
        revenue_row = revenue_result.one()

        revenue_actual = revenue_row.actual or Decimal('0')
        revenue_budget = revenue_row.budget or Decimal('0')

        # Calculate variance percent
        revenue_variance_percent = None
        if revenue_budget and revenue_budget != 0:
            revenue_variance_percent = ((revenue_actual - revenue_budget) / revenue_budget) * 100

        # Calculate COGS for Gross Margin
        cogs_query = select(
            func.sum(FinancialData.actual_amount).label('actual'),
            func.sum(FinancialData.budget_amount).label('budget')
        ).where(
            and_(
                FinancialData.organisation_id == self.organisation_id,
                FinancialData.account_category == 'COGS',
                func.extract('year', FinancialData.period_date) == year
            )
        )
        cogs_result = await self.db.execute(cogs_query)
        cogs_row = cogs_result.one()

        cogs_actual = cogs_row.actual or Decimal('0')
        cogs_budget = cogs_row.budget or Decimal('0')

        # Calculate Gross Margin %
        gross_margin_percent = None
        if revenue_actual and revenue_actual != 0:
            gross_profit = revenue_actual - cogs_actual
            gross_margin_percent = (gross_profit / revenue_actual) * 100

        gross_margin_budget_percent = None
        if revenue_budget and revenue_budget != 0:
            gross_profit_budget = revenue_budget - cogs_budget
            gross_margin_budget_percent = (gross_profit_budget / revenue_budget) * 100

        # Calculate OpEx
        opex_query = select(
            func.sum(FinancialData.actual_amount).label('actual'),
            func.sum(FinancialData.budget_amount).label('budget')
        ).where(
            and_(
                FinancialData.organisation_id == self.organisation_id,
                FinancialData.account_category == 'OpEx',
                func.extract('year', FinancialData.period_date) == year
            )
        )
        opex_result = await self.db.execute(opex_query)
        opex_row = opex_result.one()

        opex_actual = opex_row.actual or Decimal('0')
        opex_budget = opex_row.budget or Decimal('0')

        # Calculate EBITDA (simplified: Revenue - COGS - OpEx)
        ebitda = revenue_actual - cogs_actual - opex_actual
        ebitda_budget = revenue_budget - cogs_budget - opex_budget

        # Get last data date
        last_date_query = select(func.max(FinancialData.period_date)).where(
            FinancialData.organisation_id == self.organisation_id
        )
        last_date_result = await self.db.execute(last_date_query)
        last_date = last_date_result.scalar()

        return DashboardSummary(
            organisation_id=self.organisation_id,
            organisation_name=org_name,
            period=f"YTD {year}",
            revenue_ytd=revenue_actual,
            revenue_budget=revenue_budget,
            revenue_variance_percent=revenue_variance_percent,
            gross_margin_percent=gross_margin_percent,
            gross_margin_budget_percent=gross_margin_budget_percent,
            ebitda=ebitda,
            ebitda_budget=ebitda_budget,
            opex_actual=opex_actual,
            opex_budget=opex_budget,
            last_updated=datetime.now(),
            data_through_date=last_date
        )

    async def get_monthly_trends(
        self,
        category: str = 'Revenue',
        year: int = None,
        months: int = 12
    ) -> List[MonthlyTrend]:
        """Get monthly trend data for charts."""

        if year is None:
            year = datetime.now().year

        query = select(
            func.to_char(FinancialData.period_date, 'Mon').label('month'),
            func.sum(FinancialData.actual_amount).label('actual'),
            func.sum(FinancialData.budget_amount).label('budget'),
            func.sum(FinancialData.prior_year_amount).label('prior_year')
        ).where(
            and_(
                FinancialData.organisation_id == self.organisation_id,
                FinancialData.account_category == category,
                func.extract('year', FinancialData.period_date) == year
            )
        ).group_by(
            func.to_char(FinancialData.period_date, 'Mon'),
            func.extract('month', FinancialData.period_date)
        ).order_by(
            func.extract('month', FinancialData.period_date)
        ).limit(months)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            MonthlyTrend(
                period=row.month,
                actual=row.actual or Decimal('0'),
                budget=row.budget or Decimal('0'),
                prior_year=row.prior_year
            )
            for row in rows
        ]

    async def get_category_breakdown(self, year: int = None) -> List[CategoryBreakdown]:
        """Get breakdown by account category."""

        if year is None:
            year = datetime.now().year

        query = select(
            FinancialData.account_category.label('category'),
            func.sum(FinancialData.actual_amount).label('actual'),
            func.sum(FinancialData.budget_amount).label('budget')
        ).where(
            and_(
                FinancialData.organisation_id == self.organisation_id,
                func.extract('year', FinancialData.period_date) == year
            )
        ).group_by(FinancialData.account_category)

        result = await self.db.execute(query)
        rows = result.all()

        breakdown = []
        for row in rows:
            actual = row.actual or Decimal('0')
            budget = row.budget or Decimal('0')
            variance = actual - budget
            variance_percent = None
            if budget and budget != 0:
                variance_percent = (variance / budget) * 100

            breakdown.append(CategoryBreakdown(
                category=row.category,
                actual=actual,
                budget=budget,
                variance=variance,
                variance_percent=variance_percent
            ))

        return breakdown

    async def create_financial_data(self, data: FinancialDataCreate) -> FinancialData:
        """Create a single financial data record."""

        record = FinancialData(
            organisation_id=self.organisation_id,
            **data.model_dump()
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def bulk_upsert_financial_data(
        self,
        data_list: List[FinancialDataCreate]
    ) -> int:
        """Bulk upsert financial data (insert or update on conflict)."""

        if not data_list:
            return 0

        values = [
            {
                "organisation_id": self.organisation_id,
                "period_date": item.period_date,
                "period_type": item.period_type,
                "account_category": item.account_category,
                "account_name": item.account_name,
                "actual_amount": item.actual_amount,
                "budget_amount": item.budget_amount,
                "prior_year_amount": item.prior_year_amount,
                "notes": item.notes
            }
            for item in data_list
        ]

        stmt = insert(FinancialData).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=['organisation_id', 'period_date', 'account_category', 'account_name'],
            set_={
                'actual_amount': stmt.excluded.actual_amount,
                'budget_amount': stmt.excluded.budget_amount,
                'prior_year_amount': stmt.excluded.prior_year_amount,
                'notes': stmt.excluded.notes,
                'updated_at': func.now()
            }
        )

        await self.db.execute(stmt)
        await self.db.commit()

        return len(data_list)

    async def delete_all_data(self) -> int:
        """Delete all financial data for the organisation."""

        result = await self.db.execute(
            delete(FinancialData).where(
                FinancialData.organisation_id == self.organisation_id
            )
        )
        await self.db.commit()
        return result.rowcount


class CSVProcessor:
    """Process CSV uploads for financial data."""

    REQUIRED_COLUMNS = ['period_date', 'account_category', 'account_name', 'actual_amount']
    OPTIONAL_COLUMNS = ['budget_amount', 'prior_year_amount', 'notes', 'period_type']

    @classmethod
    def parse_csv(cls, file_content: bytes) -> List[FinancialDataCreate]:
        """Parse CSV content into FinancialDataCreate objects."""

        # Decode and parse CSV
        content = file_content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))

        # Validate columns
        fieldnames = reader.fieldnames or []
        missing = [col for col in cls.REQUIRED_COLUMNS if col not in fieldnames]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        data_list = []
        for row_num, row in enumerate(reader, start=2):
            try:
                # Parse date
                period_date = date.fromisoformat(row['period_date'])

                # Parse amounts
                actual = Decimal(row.get('actual_amount', '0') or '0')
                budget = Decimal(row.get('budget_amount', '0') or '0')
                prior_year = Decimal(row.get('prior_year_amount', '0') or '0')

                data_list.append(FinancialDataCreate(
                    period_date=period_date,
                    period_type=row.get('period_type', 'monthly'),
                    account_category=row['account_category'],
                    account_name=row['account_name'],
                    actual_amount=actual,
                    budget_amount=budget,
                    prior_year_amount=prior_year,
                    notes=row.get('notes')
                ))
            except Exception as e:
                raise ValueError(f"Error parsing row {row_num}: {str(e)}")

        return data_list

    @classmethod
    def generate_template(cls) -> str:
        """Generate a CSV template for users."""

        header = cls.REQUIRED_COLUMNS + cls.OPTIONAL_COLUMNS
        sample_rows = [
            {
                'period_date': '2025-01-01',
                'account_category': 'Revenue',
                'account_name': 'Product Sales',
                'actual_amount': '100000',
                'budget_amount': '95000',
                'prior_year_amount': '85000',
                'notes': 'Q1 sales',
                'period_type': 'monthly'
            },
            {
                'period_date': '2025-01-01',
                'account_category': 'COGS',
                'account_name': 'Direct Materials',
                'actual_amount': '45000',
                'budget_amount': '42000',
                'prior_year_amount': '40000',
                'notes': '',
                'period_type': 'monthly'
            },
            {
                'period_date': '2025-01-01',
                'account_category': 'OpEx',
                'account_name': 'Salaries',
                'actual_amount': '30000',
                'budget_amount': '30000',
                'prior_year_amount': '28000',
                'notes': '',
                'period_type': 'monthly'
            }
        ]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=header)
        writer.writeheader()
        writer.writerows(sample_rows)

        return output.getvalue()
