from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from datetime import date

from app.core.database import AsyncSessionLocal
from app.api.deps import get_current_user

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/reports/budget-vs-actual")
async def budget_vs_actual(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT
                COALESCE(b.account_code, fd.account_code)         AS account_code,
                COALESCE(am.account_name, fd.account_name, '')    AS account_name,
                COALESCE(am.reporting_category, 'Unmapped')       AS reporting_category,
                COALESCE(am.reporting_subcategory, '')            AS reporting_subcategory,
                COALESCE(SUM(b.amount), 0)                        AS budget,
                COALESCE(SUM(fd.net_amount), 0)                   AS actual,
                COALESCE(SUM(fd.net_amount), 0)
                    - COALESCE(SUM(b.amount), 0)                  AS variance,
                CASE
                    WHEN COALESCE(SUM(b.amount), 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(SUM(fd.net_amount), 0)
                         - COALESCE(SUM(b.amount), 0))
                        / ABS(SUM(b.amount)) * 100, 1)
                END                                               AS variance_pct
            FROM budgets b
            FULL OUTER JOIN financial_data fd
                ON  fd.organisation_id = b.organisation_id
                AND fd.account_code    = b.account_code
                AND fd.period_start   >= :period_start
                AND fd.period_end     <= :period_end
            LEFT JOIN account_mappings am
                ON  am.organisation_id = COALESCE(b.organisation_id, fd.organisation_id)
                AND am.account_code    = COALESCE(b.account_code, fd.account_code)
            WHERE COALESCE(b.organisation_id, fd.organisation_id) = :org_id
              AND (
                  (b.period_start >= :period_start AND b.period_end <= :period_end)
                  OR
                  (fd.period_start >= :period_start AND fd.period_end <= :period_end)
              )
            GROUP BY
                COALESCE(b.account_code, fd.account_code),
                COALESCE(am.account_name, fd.account_name, ''),
                COALESCE(am.reporting_category, 'Unmapped'),
                COALESCE(am.reporting_subcategory, '')
            ORDER BY reporting_category, account_code
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()
    return {"period_start": str(period_start), "period_end": str(period_end), "rows": [dict(r) for r in rows]}


@router.get("/reports/budget-vs-actual/summary")
async def budget_vs_actual_summary(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT
                COALESCE(am.reporting_category, 'Unmapped')  AS reporting_category,
                COALESCE(SUM(b.amount), 0)                   AS budget,
                COALESCE(SUM(fd.net_amount), 0)              AS actual,
                COALESCE(SUM(fd.net_amount), 0)
                    - COALESCE(SUM(b.amount), 0)             AS variance,
                CASE
                    WHEN COALESCE(SUM(b.amount), 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(SUM(fd.net_amount), 0)
                         - COALESCE(SUM(b.amount), 0))
                        / ABS(SUM(b.amount)) * 100, 1)
                END                                          AS variance_pct
            FROM budgets b
            FULL OUTER JOIN financial_data fd
                ON  fd.organisation_id = b.organisation_id
                AND fd.account_code    = b.account_code
                AND fd.period_start   >= :period_start
                AND fd.period_end     <= :period_end
            LEFT JOIN account_mappings am
                ON  am.organisation_id = COALESCE(b.organisation_id, fd.organisation_id)
                AND am.account_code    = COALESCE(b.account_code, fd.account_code)
            WHERE COALESCE(b.organisation_id, fd.organisation_id) = :org_id
              AND (
                  (b.period_start >= :period_start AND b.period_end <= :period_end)
                  OR
                  (fd.period_start >= :period_start AND fd.period_end <= :period_end)
              )
            GROUP BY COALESCE(am.reporting_category, 'Unmapped')
            ORDER BY reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()
    return {"period_start": str(period_start), "period_end": str(period_end), "summary": [dict(r) for r in rows]}


@router.get("/reports/actuals")
async def actuals(
    period_start: date,
    period_end: date,
    reporting_category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    query = """
        SELECT
            fd.account_code,
            COALESCE(fd.account_name, am.account_name, '')   AS account_name,
            COALESCE(am.reporting_category, 'Unmapped')      AS reporting_category,
            COALESCE(am.reporting_subcategory, '')           AS reporting_subcategory,
            fd.period_start,
            fd.period_end,
            fd.net_amount                                    AS actual,
            fd.currency
        FROM financial_data fd
        LEFT JOIN account_mappings am
            ON  am.organisation_id = fd.organisation_id
            AND am.account_code    = fd.account_code
        WHERE fd.organisation_id = :org_id
          AND fd.period_start   >= :period_start
          AND fd.period_end     <= :period_end
    """
    params: dict = {"org_id": org_id, "period_start": period_start, "period_end": period_end}
    if reporting_category:
        query += " AND COALESCE(am.reporting_category, 'Unmapped') = :reporting_category"
        params["reporting_category"] = reporting_category
    query += " ORDER BY fd.period_start, am.reporting_category, fd.account_code"
    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return {"period_start": str(period_start), "period_end": str(period_end), "rows": [dict(r) for r in rows]}


@router.get("/reports/trend")
async def monthly_trend(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT
                DATE_TRUNC('month', COALESCE(b.period_start, fd.period_start)) AS month,
                COALESCE(am.reporting_category, 'Unmapped')                    AS reporting_category,
                COALESCE(SUM(b.amount), 0)                                     AS budget,
                COALESCE(SUM(fd.net_amount), 0)                                AS actual,
                COALESCE(SUM(fd.net_amount), 0)
                    - COALESCE(SUM(b.amount), 0)                               AS variance
            FROM budgets b
            FULL OUTER JOIN financial_data fd
                ON  fd.organisation_id = b.organisation_id
                AND fd.account_code    = b.account_code
                AND fd.period_start   >= :period_start
                AND fd.period_end     <= :period_end
            LEFT JOIN account_mappings am
                ON  am.organisation_id = COALESCE(b.organisation_id, fd.organisation_id)
                AND am.account_code    = COALESCE(b.account_code, fd.account_code)
            WHERE COALESCE(b.organisation_id, fd.organisation_id) = :org_id
              AND (
                  (b.period_start >= :period_start AND b.period_end <= :period_end)
                  OR
                  (fd.period_start >= :period_start AND fd.period_end <= :period_end)
              )
            GROUP BY
                DATE_TRUNC('month', COALESCE(b.period_start, fd.period_start)),
                COALESCE(am.reporting_category, 'Unmapped')
            ORDER BY month, reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()
    return {"period_start": str(period_start), "period_end": str(period_end), "trend": [dict(r) for r in rows]}
