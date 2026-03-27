"""
FinSight AI - Settings router (period close / reopen)
======================================================
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


class PeriodEndBody(BaseModel):
    period_end: date


def _month_end_expr() -> str:
    """SQL expression: calendar month-end date from fiscal_year_months.month_period."""
    return (
        "(date_trunc('month', month_period::date) + interval '1 month - 1 day')::date"
    )


@router.post("/settings/close-period")
async def close_period(
    body: PeriodEndBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
    if not org_id or org_id == "None":
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    me = _month_end_expr()
    result = await db.execute(
        text(
            f"""
            SELECT id, is_closed, closed_at, closed_by, {me} AS month_end
            FROM fiscal_year_months
            WHERE organisation_id = :org_id
              AND {me} = :period_end
            LIMIT 1
            """
        ),
        {"org_id": org_id, "period_end": body.period_end},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Period not found for this organisation",
        )
    if row.get("is_closed"):
        raise HTTPException(status_code=400, detail="Period is already closed")

    closed_at = datetime.now(timezone.utc)
    closed_by = current_user.email or ""

    await db.execute(
        text(
            """
            UPDATE fiscal_year_months
            SET is_closed = TRUE,
                closed_at = :closed_at,
                closed_by = :closed_by
            WHERE id = :id
            """
        ),
        {
            "id": row["id"],
            "closed_at": closed_at,
            "closed_by": closed_by,
        },
    )
    await db.commit()

    return {
        "period_end": body.period_end.isoformat(),
        "is_closed": True,
        "closed_at": closed_at.isoformat(),
        "closed_by": closed_by,
    }


@router.post("/settings/reopen-period")
async def reopen_period(
    body: PeriodEndBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
    if not org_id or org_id == "None":
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    me = _month_end_expr()
    result = await db.execute(
        text(
            f"""
            SELECT id, is_closed, {me} AS month_end
            FROM fiscal_year_months
            WHERE organisation_id = :org_id
              AND {me} = :period_end
            LIMIT 1
            """
        ),
        {"org_id": org_id, "period_end": body.period_end},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Period not found for this organisation",
        )
    if not row.get("is_closed"):
        raise HTTPException(status_code=400, detail="Period is not currently closed")

    await db.execute(
        text(
            """
            UPDATE fiscal_year_months
            SET is_closed = FALSE,
                closed_at = NULL,
                closed_by = NULL
            WHERE id = :id
            """
        ),
        {"id": row["id"]},
    )
    await db.commit()

    return {
        "period_end": body.period_end.isoformat(),
        "is_closed": False,
    }
