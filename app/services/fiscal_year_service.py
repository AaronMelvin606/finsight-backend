"""
FinSight AI - Fiscal Year Service
==================================
Functions for managing fiscal year context, current FY lookup,
and auto-generation of fiscal_years / fiscal_year_months rows.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import date, datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


async def ensure_fiscal_months_current(db: AsyncSession, org_id: str) -> int:
    """Mark fiscal_year_months rows as completed when their month has ended.

    A month is considered completed when its month_period is before the
    first day of the current UTC month (same logic as generate_fy_rows).

    Returns the number of rows updated.
    """
    first_of_current_month = datetime.utcnow().date().replace(day=1).strftime("%Y-%m")

    result = await db.execute(
        text(
            "UPDATE fiscal_year_months "
            "SET is_completed = true "
            "WHERE organisation_id = :org_id "
            "  AND is_completed = false "
            "  AND month_period < :cutoff"
        ),
        {"org_id": org_id, "cutoff": first_of_current_month},
    )
    updated = result.rowcount
    if updated:
        await db.commit()
        logger.info(
            f"[FISCAL] Marked {updated} fiscal month(s) complete for org={org_id}"
        )
    return updated


async def get_last_closed_period_end_date(db: AsyncSession, org_id: str) -> Optional[date]:
    """Latest calendar month-end among fiscal_year_months rows marked closed for this org."""
    result = await db.execute(
        text(
            """
            SELECT (
                date_trunc('month', month_period::date) + interval '1 month - 1 day'
            )::date AS month_end
            FROM fiscal_year_months
            WHERE organisation_id = :org_id AND is_closed = TRUE
            ORDER BY month_end DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id},
    )
    row = result.mappings().first()
    if not row or row["month_end"] is None:
        return None
    v = row["month_end"]
    if isinstance(v, date):
        return v
    if hasattr(v, "date"):
        return v.date()
    return None


async def get_current_fy(db: AsyncSession, org_id: str) -> dict:
    """Return the current fiscal year row for an organisation.

    Falls back to a calculated FY using fy_start_month=4 if no row exists.
    """
    result = await db.execute(
        text(
            "SELECT fy_label, fy_year, start_date, end_date "
            "FROM fiscal_years "
            "WHERE organisation_id = :org_id AND is_current = true "
            "LIMIT 1"
        ),
        {"org_id": org_id},
    )
    row = result.mappings().first()
    if row:
        return dict(row)

    # Fallback: calculate from today with default fy_start_month=4
    today = date.today()
    fy_start_month = 4
    if today.month >= fy_start_month:
        fy_year = today.year
    else:
        fy_year = today.year - 1
    fy_label = f"FY{fy_year % 100:02d}"
    start_date = date(fy_year, fy_start_month, 1)
    end_date = date(fy_year + 1, fy_start_month, 1)
    return {
        "fy_label": fy_label,
        "fy_year": fy_year,
        "start_date": start_date,
        "end_date": end_date,
    }


async def get_fy_context(db: AsyncSession, org_id: str) -> dict:
    """Return full fiscal year context for the current organisation.

    Includes elapsed/total months and prior FY label for commentary modules.
    """
    fy = await get_current_fy(db, org_id)

    result = await db.execute(
        text(
            "SELECT "
            "  COUNT(*) AS months_total, "
            "  COUNT(*) FILTER (WHERE is_completed = true) AS months_elapsed "
            "FROM fiscal_year_months "
            "WHERE organisation_id = :org_id AND fy_year = :fy_year"
        ),
        {"org_id": org_id, "fy_year": fy["fy_year"]},
    )
    row = result.mappings().first()
    months_total = int(row["months_total"]) if row and row["months_total"] else 12
    months_elapsed = int(row["months_elapsed"]) if row and row["months_elapsed"] else 0

    # If no fiscal_year_months rows exist yet, default to 12
    if months_total == 0:
        months_total = 12

    prior_fy_label = "FY" + str((fy["fy_year"] - 1) % 100).zfill(2)

    start_date = fy["start_date"]
    end_date = fy["end_date"]

    last_closed = await get_last_closed_period_end_date(db, org_id)

    return {
        "fy_label": fy["fy_label"],
        "fy_year": fy["fy_year"],
        "start_date": start_date.isoformat() if isinstance(start_date, date) else str(start_date),
        "end_date": end_date.isoformat() if isinstance(end_date, date) else str(end_date),
        "months_elapsed": months_elapsed,
        "months_total": months_total,
        "prior_fy_label": prior_fy_label,
        "is_near_year_end": months_elapsed >= 10,
        "last_closed_period_end": last_closed.isoformat() if last_closed else None,
    }


async def generate_fy_rows(db: AsyncSession, org_id: str, fy_start_month: int = 4) -> None:
    """Generate fiscal_years and fiscal_year_months rows for an organisation.

    Covers 5 years back and 1 year forward from today.
    FY year = calendar year of the FY start month.
    """
    today = date.today()

    # Determine current FY year
    if today.month >= fy_start_month:
        current_fy_year = today.year
    else:
        current_fy_year = today.year - 1

    fy_years = range(current_fy_year - 5, current_fy_year + 2)  # 5 back + current + 1 forward

    # Reset all existing rows to is_current = false
    await db.execute(
        text("UPDATE fiscal_years SET is_current = false WHERE organisation_id = :org_id"),
        {"org_id": org_id},
    )

    # Insert fiscal_years rows
    for fy_year in fy_years:
        fy_label = f"FY{fy_year % 100:02d}"
        start_date = date(fy_year, fy_start_month, 1)
        # End date is first day of start month in the next year
        end_date = date(fy_year + 1, fy_start_month, 1)
        is_current = fy_year == current_fy_year

        await db.execute(
            text(
                "INSERT INTO fiscal_years (organisation_id, fy_year, fy_label, start_date, end_date, is_current) "
                "VALUES (:org_id, :fy_year, :fy_label, :start_date, :end_date, :is_current) "
                "ON CONFLICT (organisation_id, fy_year) "
                "DO UPDATE SET is_current = EXCLUDED.is_current"
            ),
            {
                "org_id": org_id,
                "fy_year": fy_year,
                "fy_label": fy_label,
                "start_date": start_date,
                "end_date": end_date,
                "is_current": is_current,
            },
        )

    # Insert fiscal_year_months rows
    first_of_current_month = today.replace(day=1)
    for fy_year in fy_years:
        month = fy_start_month
        year = fy_year
        for i in range(12):
            month_date = date(year, month, 1)
            is_completed = month_date < first_of_current_month

            await db.execute(
                text(
                    "INSERT INTO fiscal_year_months "
                    "(organisation_id, fy_year, month_period, month_index, is_completed) "
                    "VALUES (:org_id, :fy_year, :month_period, :month_index, :is_completed) "
                    "ON CONFLICT (organisation_id, month_period) DO NOTHING"
                ),
                {
                    "org_id": org_id,
                    "fy_year": fy_year,
                    "month_period": month_date,
                    "month_index": i + 1,
                    "is_completed": is_completed,
                },
            )

            # Advance to next month
            month += 1
            if month > 12:
                month = 1
                year += 1

    await db.commit()
