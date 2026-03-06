from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from datetime import date

from app.core.database import AsyncSessionLocal
from app.api.deps import get_current_user

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


class BudgetEntry(BaseModel):
    account_code: str
    period_start: date
    period_end: date
    amount: float
    notes: Optional[str] = ""


class BudgetUpdate(BaseModel):
    amount: float
    notes: Optional[str] = None


@router.get("/budgets")
async def list_budgets(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    query = """
        SELECT id, account_code, period_start, period_end, amount, notes,
               created_at, updated_at
        FROM budgets
        WHERE organisation_id = :org_id
    """
    params: dict = {"org_id": org_id}
    if period_start:
        query += " AND period_start >= :period_start"
        params["period_start"] = period_start
    if period_end:
        query += " AND period_end <= :period_end"
        params["period_end"] = period_end
    query += " ORDER BY period_start, account_code"
    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return {"budgets": [dict(r) for r in rows]}


@router.post("/budgets", status_code=201)
async def create_budget(
    payload: BudgetEntry,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            INSERT INTO budgets
                (organisation_id, account_code, period_start, period_end, amount, notes)
            VALUES
                (:org_id, :account_code, :period_start, :period_end, :amount, :notes)
            ON CONFLICT (organisation_id, account_code, period_start, period_end)
            DO UPDATE SET
                amount     = EXCLUDED.amount,
                notes      = EXCLUDED.notes,
                updated_at = now()
            RETURNING id
        """),
        {
            "org_id": org_id,
            "account_code": payload.account_code,
            "period_start": payload.period_start,
            "period_end": payload.period_end,
            "amount": payload.amount,
            "notes": payload.notes,
        },
    )
    await db.commit()
    row = result.fetchone()
    return {"message": "Budget entry saved", "id": str(row[0])}


@router.post("/budgets/bulk", status_code=201)
async def bulk_create_budgets(
    payload: list[BudgetEntry],
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    if not payload:
        raise HTTPException(status_code=400, detail="No budget entries provided")
    count = 0
    for entry in payload:
        await db.execute(
            text("""
                INSERT INTO budgets
                    (organisation_id, account_code, period_start, period_end, amount, notes)
                VALUES
                    (:org_id, :account_code, :period_start, :period_end, :amount, :notes)
                ON CONFLICT (organisation_id, account_code, period_start, period_end)
                DO UPDATE SET
                    amount     = EXCLUDED.amount,
                    notes      = EXCLUDED.notes,
                    updated_at = now()
            """),
            {
                "org_id": org_id,
                "account_code": entry.account_code,
                "period_start": entry.period_start,
                "period_end": entry.period_end,
                "amount": entry.amount,
                "notes": entry.notes,
            },
        )
        count += 1
    await db.commit()
    return {"message": f"{count} budget entries saved"}


@router.patch("/budgets/{budget_id}")
async def update_budget(
    budget_id: str,
    payload: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    set_clauses = ["amount = :amount", "updated_at = now()"]
    params: dict = {"org_id": org_id, "budget_id": budget_id, "amount": payload.amount}
    if payload.notes is not None:
        set_clauses.append("notes = :notes")
        params["notes"] = payload.notes
    result = await db.execute(
        text(f"""
            UPDATE budgets
            SET {', '.join(set_clauses)}
            WHERE id = :budget_id
              AND organisation_id = :org_id
            RETURNING id
        """),
        params,
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Budget entry not found")
    return {"message": "Budget entry updated", "id": budget_id}


@router.delete("/budgets/{budget_id}", status_code=200)
async def delete_budget(
    budget_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            DELETE FROM budgets
            WHERE id = :budget_id
              AND organisation_id = :org_id
            RETURNING id
        """),
        {"budget_id": budget_id, "org_id": org_id},
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Budget entry not found")
    return {"message": "Budget entry deleted"}


@router.get("/budgets/periods")
async def list_budget_periods(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT DISTINCT period_start, period_end
            FROM budgets
            WHERE organisation_id = :org_id
            ORDER BY period_start
        """),
        {"org_id": org_id},
    )
    rows = result.mappings().all()
    return {"periods": [dict(r) for r in rows]}
