"""
FinSight AI - Budgets Router (Workstream 3)
============================================
Budget CRUD endpoints.
Fixed to use User ORM object and correct budgets table columns.
CSV bulk upload supported.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from datetime import date
import io
import csv

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


class BudgetEntry(BaseModel):
    account_code: str
    account_name: str
    period_start: date
    period_end: date
    amount: float
    budget_name: Optional[str] = "Default Budget"


class BudgetUpdate(BaseModel):
    amount: float


# ──────────────────────────────────────────────────────────────────────
# LIST BUDGETS
# ──────────────────────────────────────────────────────────────────────

@router.get("/budgets")
async def list_budgets(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
    query = """
        SELECT id, budget_name, account_code, account_name,
               period_start, period_end, amount,
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


# ──────────────────────────────────────────────────────────────────────
# CREATE BUDGET
# ──────────────────────────────────────────────────────────────────────

@router.post("/budgets", status_code=201)
async def create_budget(
    payload: BudgetEntry,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
    result = await db.execute(
        text("""
            INSERT INTO budgets
                (organisation_id, budget_name, account_code, account_name,
                 period_start, period_end, amount)
            VALUES
                (:org_id, :budget_name, :account_code, :account_name,
                 :period_start, :period_end, :amount)
            RETURNING id
        """),
        {
            "org_id": org_id,
            "budget_name": payload.budget_name,
            "account_code": payload.account_code,
            "account_name": payload.account_name,
            "period_start": payload.period_start,
            "period_end": payload.period_end,
            "amount": payload.amount,
        },
    )
    await db.commit()
    row = result.fetchone()
    return {"message": "Budget entry saved", "id": str(row[0])}


# ──────────────────────────────────────────────────────────────────────
# BULK CREATE BUDGETS (CSV upload)
# ──────────────────────────────────────────────────────────────────────

@router.post("/budgets/bulk", status_code=201)
async def bulk_create_budgets(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    count = 0
    for row in reader:
        amount_str = row.get("amount", "").strip()
        if not amount_str:
            continue
        await db.execute(
            text("""
                INSERT INTO budgets
                    (organisation_id, budget_name, account_code, account_name,
                     period_start, period_end, amount)
                VALUES
                    (:org_id, :budget_name, :account_code, :account_name,
                     :period_start, :period_end, :amount)
                ON CONFLICT (organisation_id, account_code, period_start)
                DO UPDATE SET amount = EXCLUDED.amount, updated_at = now()
            """),
            {
                "org_id": org_id,
                "budget_name": "Default Budget",
                "account_code": row["account_code"].strip(),
                "account_name": row["account_name"].strip(),
                "period_start": row["period_start"].strip(),
                "period_end": row["period_end"].strip(),
                "amount": float(amount_str),
            },
        )
        count += 1

    await db.commit()
    return {"message": f"{count} budget entries saved"}


# ──────────────────────────────────────────────────────────────────────
# UPDATE BUDGET
# ──────────────────────────────────────────────────────────────────────

@router.patch("/budgets/{budget_id}")
async def update_budget(
    budget_id: str,
    payload: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
    result = await db.execute(
        text("""
            UPDATE budgets
            SET amount = :amount, updated_at = now()
            WHERE id = :budget_id
              AND organisation_id = :org_id
            RETURNING id
        """),
        {"org_id": org_id, "budget_id": budget_id, "amount": payload.amount},
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Budget entry not found")
    return {"message": "Budget entry updated", "id": budget_id}


# ──────────────────────────────────────────────────────────────────────
# DELETE BUDGET
# ──────────────────────────────────────────────────────────────────────

@router.delete("/budgets/{budget_id}", status_code=200)
async def delete_budget(
    budget_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
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


# ──────────────────────────────────────────────────────────────────────
# LIST BUDGET PERIODS
# ──────────────────────────────────────────────────────────────────────

@router.get("/budgets/periods")
async def list_budget_periods(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)
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


# ──────────────────────────────────────────────────────────────────────
# BUDGET TEMPLATE (CSV download)
# ──────────────────────────────────────────────────────────────────────

@router.get("/budgets/template")
async def budget_template(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.organisation_id)

    result = await db.execute(
        text("""
            SELECT account_code, account_name, reporting_category
            FROM account_mappings
            WHERE organisation_id = :org_id
              AND include_in_pnl = TRUE
              AND is_mapped = TRUE
            ORDER BY reporting_category, account_code
        """),
        {"org_id": org_id},
    )
    accounts = result.mappings().all()

    if not accounts:
        raise HTTPException(status_code=404, detail="No mapped P&L accounts found")

    from dateutil.relativedelta import relativedelta
    periods = []
    current = period_start.replace(day=1)
    while current <= period_end:
        month_end = (current + relativedelta(months=1)) - relativedelta(days=1)
        if month_end > period_end:
            month_end = period_end
        periods.append((current, month_end))
        current = current + relativedelta(months=1)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["account_code", "account_name", "reporting_category",
                     "period_start", "period_end", "amount"])

    for account in accounts:
        for p_start, p_end in periods:
            writer.writerow([
                account["account_code"],
                account["account_name"],
                account["reporting_category"],
                str(p_start),
                str(p_end),
                "",
            ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=finsight_budget_template.csv"},
    )