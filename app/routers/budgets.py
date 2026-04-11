"""
FinSight AI - Budgets Router
=============================
Monthly budget CRUD endpoints.
One row per account per month — required for AvB joins against Xero actuals.

CSV upload format:
    account_code,account_name,reporting_category,fiscal_year,budget_month,amount
    200,Sales,Revenue,2026,4,45000
    200,Sales,Revenue,2026,5,48000
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from pydantic import BaseModel, validator
from typing import Optional
import io
import csv

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.budget_service import fy_periods_for_range
from app.services.fiscal_year_service import get_fy_start_month

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────────────────────────────────

class BudgetEntry(BaseModel):
    account_code: str
    account_name: str
    reporting_category: Optional[str] = None
    fiscal_year: int
    budget_month: int          # 1–12
    amount: float
    budget_name: Optional[str] = "Default Budget"

    @validator("budget_month")
    def validate_month(cls, v):
        if not 1 <= v <= 12:
            raise ValueError("budget_month must be between 1 and 12")
        return v


class BudgetUpdate(BaseModel):
    amount: float


# ──────────────────────────────────────────────────────────────────────
# LIST BUDGETS
# ──────────────────────────────────────────────────────────────────────

@router.get("/budgets")
async def list_budgets(
    fiscal_year: Optional[int] = None,
    budget_month: Optional[int] = None,
    reporting_category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.active_org_id)
    query = """
        SELECT id, budget_name, account_code, account_name,
               reporting_category, fiscal_year, budget_month, amount,
               created_at, updated_at
        FROM budgets
        WHERE organisation_id = :org_id
    """
    params: dict = {"org_id": org_id}

    if fiscal_year:
        query += " AND fiscal_year = :fiscal_year"
        params["fiscal_year"] = fiscal_year
    if budget_month:
        query += " AND budget_month = :budget_month"
        params["budget_month"] = budget_month
    if reporting_category:
        query += " AND reporting_category = :reporting_category"
        params["reporting_category"] = reporting_category

    query += " ORDER BY fiscal_year, budget_month, account_code"

    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return {"budgets": [dict(r) for r in rows]}


# ──────────────────────────────────────────────────────────────────────
# CREATE SINGLE BUDGET ENTRY
# ──────────────────────────────────────────────────────────────────────

@router.post("/budgets", status_code=201)
async def create_budget(
    payload: BudgetEntry,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = str(current_user.active_org_id)
    result = await db.execute(
        text("""
            INSERT INTO budgets
                (organisation_id, budget_name, account_code, account_name,
                 reporting_category, fiscal_year, budget_month, amount,
                 period_start, period_end)
            VALUES
                (:org_id, :budget_name, :account_code, :account_name,
                 :reporting_category, :fiscal_year, :budget_month, :amount,
                 make_date(:fiscal_year, :budget_month, 1),
                 (make_date(:fiscal_year, :budget_month, 1) + interval '1 month - 1 day')::date)
            ON CONFLICT (organisation_id, account_code, fiscal_year, budget_month)
            DO UPDATE SET
                amount = EXCLUDED.amount,
                reporting_category = EXCLUDED.reporting_category,
                budget_name = EXCLUDED.budget_name,
                updated_at = now()
            RETURNING id
        """),
        {
            "org_id": org_id,
            "budget_name": payload.budget_name,
            "account_code": payload.account_code,
            "account_name": payload.account_name,
            "reporting_category": payload.reporting_category,
            "fiscal_year": payload.fiscal_year,
            "budget_month": payload.budget_month,
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
    """
    Upload a monthly budget CSV.

    Required columns:
        account_code, account_name, reporting_category, fiscal_year, budget_month, amount

    Optional column:
        budget_name (defaults to "Default Budget")

    Upserts on (organisation_id, account_code, fiscal_year, budget_month).
    """
    org_id = str(current_user.active_org_id)

    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    required_columns = {"account_code", "account_name", "fiscal_year", "budget_month", "amount"}
    if reader.fieldnames:
        missing = required_columns - {f.strip() for f in reader.fieldnames}
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"CSV missing required columns: {', '.join(sorted(missing))}"
            )

    count = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        try:
            amount_str = row.get("amount", "").strip()
            if not amount_str:
                continue

            fiscal_year = int(row["fiscal_year"].strip())
            budget_month = int(row["budget_month"].strip())

            if not 1 <= budget_month <= 12:
                errors.append({"row": i, "error": f"budget_month {budget_month} is not 1–12"})
                continue

            await db.execute(
                text("""
                    INSERT INTO budgets
                        (organisation_id, budget_name, account_code, account_name,
                         reporting_category, fiscal_year, budget_month, amount,
                         period_start, period_end)
                    VALUES
                        (:org_id, :budget_name, :account_code, :account_name,
                         :reporting_category, :fiscal_year, :budget_month, :amount,
                         make_date(:fiscal_year, :budget_month, 1),
                         (make_date(:fiscal_year, :budget_month, 1) + interval '1 month - 1 day')::date)
                    ON CONFLICT (organisation_id, account_code, fiscal_year, budget_month)
                    DO UPDATE SET
                        amount = EXCLUDED.amount,
                        reporting_category = EXCLUDED.reporting_category,
                        budget_name = EXCLUDED.budget_name,
                        updated_at = now()
                """),
                {
                    "org_id": org_id,
                    "budget_name": row.get("budget_name", "Default Budget").strip() or "Default Budget",
                    "account_code": row["account_code"].strip(),
                    "account_name": row["account_name"].strip(),
                    "reporting_category": row.get("reporting_category", "").strip() or None,
                    "fiscal_year": fiscal_year,
                    "budget_month": budget_month,
                    "amount": float(amount_str),
                },
            )
            count += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})

    await db.commit()

    if errors:
        return {"message": f"{count} entries saved", "errors": errors}

    return {"message": f"{count} budget entries saved successfully"}


# ──────────────────────────────────────────────────────────────────────
# DOWNLOAD CSV TEMPLATE
# ──────────────────────────────────────────────────────────────────────

@router.get("/budgets/template")
async def download_budget_template(
    current_user: User = Depends(get_current_user),
):
    """
    Download a blank CSV template for budget upload.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "account_code", "account_name", "reporting_category",
        "fiscal_year", "budget_month", "amount", "budget_name"
    ])
    # Example rows covering Apr–Jun (months 4–6) for FY2026
    writer.writerow(["200", "Sales", "Revenue", "2026", "4", "45000", "FY26 Budget"])
    writer.writerow(["200", "Sales", "Revenue", "2026", "5", "48000", "FY26 Budget"])
    writer.writerow(["200", "Sales", "Revenue", "2026", "6", "47000", "FY26 Budget"])
    writer.writerow(["400", "Cost of Sales", "Cost of Sales", "2026", "4", "18000", "FY26 Budget"])
    writer.writerow(["400", "Cost of Sales", "Cost of Sales", "2026", "5", "19200", "FY26 Budget"])
    writer.writerow(["400", "Cost of Sales", "Cost of Sales", "2026", "6", "18800", "FY26 Budget"])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=finsight_budget_template.csv"}
    )


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
    org_id = str(current_user.active_org_id)
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
    org_id = str(current_user.active_org_id)
    result = await db.execute(
        text("""
            DELETE FROM budgets
            WHERE id = :budget_id
              AND organisation_id = :org_id
            RETURNING id
        """),
        {"org_id": org_id, "budget_id": budget_id},
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Budget entry not found")
    return {"message": "Budget entry deleted", "id": budget_id}


# ──────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────
# GENERATE BUDGET FROM PRIOR YEAR ACTUALS
# ──────────────────────────────────────────────────────────────────────

@router.post("/budgets/generate-from-actuals", status_code=201)
async def generate_from_actuals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Auto-generate current FY budget from prior year actuals.

    Reads financial_line_items for the prior FY (e.g. FY25 = 2025-04 to 2026-03),
    maps each account+month to the current FY (e.g. FY26 = 2026-04 to 2027-03),
    and writes to budget_monthly with source = 'auto_prior_year'.

    Returns 409 if the current FY already has budget rows.
    Returns 404 if no prior year actuals exist.
    """
    org_id = str(current_user.active_org_id)
    if not org_id or org_id == "None":
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    # Determine current and prior FY
    fy_start_month = await get_fy_start_month(db, org_id)
    today = date.today()
    if today.month >= fy_start_month:
        current_fy_year = today.year
    else:
        current_fy_year = today.year - 1
    prior_fy_year = current_fy_year - 1

    # Current FY period range (e.g. 2026-04 to 2027-03)
    current_fy_start = date(current_fy_year, fy_start_month, 1)
    current_fy_end = date(current_fy_year + 1, fy_start_month, 1) - timedelta(days=1)
    current_fy_periods = fy_periods_for_range(current_fy_start, current_fy_end)

    # Prior FY period range (e.g. 2025-04 to 2026-03)
    prior_fy_start = date(prior_fy_year, fy_start_month, 1)
    prior_fy_end = date(prior_fy_year + 1, fy_start_month, 1) - timedelta(days=1)

    # Guard: check if current FY already has budget rows
    existing = await db.execute(
        text("""
            SELECT COUNT(*) FROM budget_monthly
            WHERE organisation_id = :org_id
              AND period IN :periods
        """).bindparams(bindparam("periods", expanding=True)),
        {"org_id": org_id, "periods": current_fy_periods},
    )
    if int(existing.scalar() or 0) > 0:
        fy_label = f"FY{current_fy_year % 100}"
        raise HTTPException(
            status_code=409,
            detail=f"{fy_label} budget already exists. Delete existing budget first or upload a replacement.",
        )

    # Query prior FY actuals grouped by account_code + month
    actuals_result = await db.execute(
        text("""
            SELECT
                am.account_code,
                am.account_name,
                am.reporting_category,
                TO_CHAR(fli.period_start, 'YYYY-MM') AS period,
                SUM(fli.net_amount) AS actual
            FROM financial_line_items fli
            JOIN account_mappings am
                ON  am.organisation_id = fli.organisation_id
                AND am.xero_account_id = fli.xero_account_id
            WHERE fli.organisation_id = :org_id
              AND fli.report_type = 'ProfitAndLoss'
              AND fli.period_start >= :prior_start
              AND fli.period_end <= :prior_end
              AND am.statement_type = 'profit_and_loss'
              AND am.include_in_pnl = TRUE
            GROUP BY am.account_code, am.account_name,
                     am.reporting_category, TO_CHAR(fli.period_start, 'YYYY-MM')
        """),
        {
            "org_id": org_id,
            "prior_start": prior_fy_start,
            "prior_end": prior_fy_end,
        },
    )
    rows = actuals_result.mappings().all()

    if not rows:
        fy_label = f"FY{prior_fy_year % 100}"
        raise HTTPException(
            status_code=404,
            detail=f"No actuals found for {fy_label}. Connect Xero and sync data first.",
        )

    # Map prior FY periods to current FY (+1 year) and insert
    rows_created = 0
    months_seen: set = set()

    for row in rows:
        prior_period = row["period"]  # e.g. "2025-04"
        months_seen.add(prior_period)

        # Shift +1 year: "2025-04" -> "2026-04"
        prior_year = int(prior_period[:4])
        month_part = prior_period[5:]  # "04"
        new_period = f"{prior_year + 1}-{month_part}"

        await db.execute(
            text("""
                INSERT INTO budget_monthly
                    (id, organisation_id, account_code, account_name,
                     reporting_category, period, budget_amount, source,
                     created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :org_id, :account_code, :account_name,
                     :reporting_category, :period, :amount, 'auto_prior_year',
                     now(), now())
                ON CONFLICT (organisation_id, account_code, period)
                DO UPDATE SET
                    budget_amount = EXCLUDED.budget_amount,
                    account_name = EXCLUDED.account_name,
                    reporting_category = EXCLUDED.reporting_category,
                    source = EXCLUDED.source,
                    updated_at = now()
            """),
            {
                "org_id": org_id,
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "reporting_category": row["reporting_category"],
                "period": new_period,
                "amount": float(row["actual"]),
            },
        )
        rows_created += 1

    await db.commit()

    months_available = len(months_seen)
    fy_label = f"FY{current_fy_year % 100}"

    return {
        "success": True,
        "rows_created": rows_created,
        "months_available": months_available,
        "fy_label": fy_label,
        "coverage": "full" if months_available >= 12 else "partial",
        "source": "auto_prior_year",
    }