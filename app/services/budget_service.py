"""
FinSight AI - Budget Service
=============================
Shared budget utilities for boundary detection and source tracking.
Used by reports.py (AvB endpoints) and commentary.py (skip logic).
"""

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession


def fy_periods_for_range(fy_start: date, fy_end: date) -> list[str]:
    """Return list of YYYY-MM strings for every month in [fy_start, fy_end]."""
    periods: list[str] = []
    y, m = fy_start.year, fy_start.month
    end_y, end_m = fy_end.year, fy_end.month
    while (y, m) <= (end_y, end_m):
        periods.append(f"{y}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return periods


async def get_budget_status(
    db: AsyncSession, org_id: str, fy_start: date, fy_end: date
) -> str:
    """Check budget coverage for the given FY.

    Returns:
        "no_budget"      — zero budget_monthly rows for any month in the FY
        "partial_budget"  — some but not all 12 months have budget rows
        "full_budget"     — all 12 months have at least one budget row
    """
    periods = fy_periods_for_range(fy_start, fy_end)

    result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT period) AS months_with_budget
            FROM budget_monthly
            WHERE organisation_id = :org_id
              AND period IN :periods
        """).bindparams(bindparam("periods", expanding=True)),
        {"org_id": org_id, "periods": periods},
    )
    months_with_budget = int(result.scalar() or 0)

    if months_with_budget == 0:
        return "no_budget"
    elif months_with_budget >= len(periods):
        return "full_budget"
    else:
        return "partial_budget"


async def get_budget_source(
    db: AsyncSession, org_id: str, fy_periods: list[str]
) -> Optional[str]:
    """Return the dominant source value for budget rows in the given FY periods.

    Returns the most common source value, or None if no rows or all source values are NULL.
    """
    if not fy_periods:
        return None

    result = await db.execute(
        text("""
            SELECT source, COUNT(*) AS cnt
            FROM budget_monthly
            WHERE organisation_id = :org_id
              AND period IN :periods
              AND source IS NOT NULL
            GROUP BY source
            ORDER BY cnt DESC
            LIMIT 1
        """).bindparams(bindparam("periods", expanding=True)),
        {"org_id": org_id, "periods": fy_periods},
    )
    row = result.mappings().fetchone()
    if row:
        return row["source"]
    return None
