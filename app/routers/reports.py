"""
FinSight AI - Reports Router (Workstream 3)
============================================
Actual vs Budget reporting endpoints.
Queries financial_line_items (normalised) joined to account_mappings and budgets.
All financial calculations performed server-side.

FIX (v2): Pre-aggregate financial_line_items into fli_agg CTE before joining to
account_mappings. Previously, accounts with multiple mapping rows caused the
actuals JOIN to fan out, producing duplicate rows per account per period.
"""

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from typing import Optional
from datetime import date
import io
import csv

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()

# CSV month columns (Apr–Mar order); FY start April = default.
BUDGET_CSV_MONTH_COLUMNS = [
    "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "jan", "feb", "mar",
]
# Month name -> calendar month number (1–12)
_MONTH_NAME_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# For FY start April: month 4–12 = FY year Y, month 1–3 = FY year Y+1
FY_START_MONTH = 4


def _period_for_fy_month(fiscal_year: int, month_name: str) -> str:
    """Return YYYY-MM for the given FY year and month column (apr..mar)."""
    month_num = _MONTH_NAME_TO_NUM[month_name.lower()]
    if month_num >= FY_START_MONTH:
        year = fiscal_year
    else:
        year = fiscal_year + 1
    return f"{year}-{month_num:02d}"


# ──────────────────────────────────────────────────────────────────────
# BUDGET UPLOAD (budget_monthly)
# ──────────────────────────────────────────────────────────────────────

@router.post("/reports/budget/upload", status_code=200)
async def budget_upload(
    file: UploadFile = File(...),
    fiscal_year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a budget CSV into budget_monthly (AvB canonical table).

    CSV format: account_code, account_name, apr, may, jun, jul, aug, sep, oct, nov, dec, jan, feb, mar
    Month columns must be numeric. Account codes must exist in the organisation's account_mappings.
    organisation_id is taken from the JWT; re-uploading overwrites (upsert by org + account_code + period).

    Optional query param: fiscal_year (default: current FY with April start).
    """
    org_id = str(current_user.organisation_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    # Default fiscal year: April start → current FY
    today = date.today()
    if fiscal_year is None:
        fiscal_year = today.year if today.month >= FY_START_MONTH else today.year - 1

    # Load valid account codes and reporting_category from account_mappings
    result = await db.execute(
        text("""
            SELECT account_code, account_name, reporting_category
            FROM account_mappings
            WHERE organisation_id = :org_id
        """),
        {"org_id": org_id},
    )
    mapping_rows = result.mappings().all()
    valid_accounts = {r["account_code"].strip(): {"account_name": r["account_name"], "reporting_category": r["reporting_category"]} for r in mapping_rows if r.get("account_code")}

    if not valid_accounts:
        raise HTTPException(
            status_code=400,
            detail="No account mappings found for this organisation. Sync Chart of Accounts from Xero first.",
        )

    required_columns = {"account_code", "account_name"} | set(BUDGET_CSV_MONTH_COLUMNS)
    contents = await file.read()
    try:
        decoded = contents.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV has no header row")
    normalized_headers = {h.strip().lower(): h for h in reader.fieldnames}
    missing = required_columns - set(normalized_headers.keys())
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV missing required columns: {', '.join(sorted(missing))}. Expected: account_code, account_name, apr, may, jun, jul, aug, sep, oct, nov, dec, jan, feb, mar",
        )

    rows_accepted = 0
    rows_rejected: list[dict] = []
    total_budget_loaded: float = 0.0

    def get_cell(row: dict, col: str) -> str:
        key = normalized_headers.get(col, col)
        return (row.get(key) or "").strip()

    for row_index, row in enumerate(reader, start=2):
        raw_code = get_cell(row, "account_code")
        raw_name = get_cell(row, "account_name")
        if not raw_code:
            rows_rejected.append({"row": row_index, "reason": "Missing account_code"})
            continue
        if raw_code not in valid_accounts:
            rows_rejected.append({"row": row_index, "reason": f"account_code '{raw_code}' not in organisation's account_mappings"})
            continue
        info = valid_accounts[raw_code]
        account_name = raw_name or (info["account_name"] or "")
        reporting_category = info["reporting_category"] or ""

        for month_col in BUDGET_CSV_MONTH_COLUMNS:
            val = get_cell(row, month_col)
            if not val:
                continue
            try:
                amount = float(val)
            except ValueError:
                rows_rejected.append({"row": row_index, "reason": f"Non-numeric value in column '{month_col}': {val[:50]}"})
                continue
            period = _period_for_fy_month(fiscal_year, month_col)
            total_budget_loaded += amount
            await db.execute(
                text("""
                    INSERT INTO budget_monthly
                        (organisation_id, account_code, account_name, reporting_category, period, budget_amount, updated_at)
                    VALUES
                        (:org_id, :account_code, :account_name, :reporting_category, :period, :budget_amount, now())
                    ON CONFLICT (organisation_id, account_code, period)
                    DO UPDATE SET
                        account_name = EXCLUDED.account_name,
                        reporting_category = EXCLUDED.reporting_category,
                        budget_amount = EXCLUDED.budget_amount,
                        updated_at = now()
                """),
                {
                    "org_id": org_id,
                    "account_code": raw_code,
                    "account_name": account_name,
                    "reporting_category": reporting_category,
                    "period": period,
                    "budget_amount": amount,
                },
            )
            rows_accepted += 1

    await db.commit()

    return {
        "rows_accepted": rows_accepted,
        "rows_rejected": rows_rejected,
        "total_budget_loaded": round(total_budget_loaded, 2),
        "fiscal_year": fiscal_year,
    }


# ──────────────────────────────────────────────────────────────────────
# ACTUAL VS BUDGET - DETAIL
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/avb")
async def actual_vs_budget(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Actual vs Budget detail by account.
    Returns one row per P&L account that has either actuals or budgets in the period.
    """
    org_id = str(current_user.organisation_id)

    result = await db.execute(
        text("""
            WITH fli_agg AS (
                -- Pre-aggregate actuals to one row per (xero_account_id)
                -- across the full requested period before joining to mappings.
                -- This prevents fan-out when account_mappings has multiple rows
                -- for the same xero_account_id.
                SELECT
                    organisation_id,
                    xero_account_id,
                    SUM(net_amount) AS net_amount
                FROM financial_line_items
                WHERE organisation_id = :org_id
                  AND report_type     = 'ProfitAndLoss'
                  AND period_start   >= :period_start
                  AND period_end     <= :period_end
                GROUP BY organisation_id, xero_account_id
            ),
            b_agg AS (
                -- Pre-aggregate budgets to one row per account_code
                -- across the full requested period.
                SELECT organisation_id, account_code, SUM(amount) AS total_budget
                FROM budgets
                WHERE organisation_id = :org_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                GROUP BY organisation_id, account_code
            )
            SELECT
                am.reporting_category,
                am.account_code,
                am.account_name,
                COALESCE(fli_agg.net_amount, 0)           AS actual,
                COALESCE(b_agg.total_budget, 0)           AS budget,
                COALESCE(fli_agg.net_amount, 0)
                    - COALESCE(b_agg.total_budget, 0)     AS variance,
                CASE
                    WHEN COALESCE(b_agg.total_budget, 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(fli_agg.net_amount, 0) - COALESCE(b_agg.total_budget, 0))
                        / ABS(b_agg.total_budget) * 100, 1
                    )
                END AS variance_pct
            FROM account_mappings am
            LEFT JOIN fli_agg
                ON  fli_agg.organisation_id = am.organisation_id
                AND fli_agg.xero_account_id = am.xero_account_id
            LEFT JOIN b_agg
                ON  b_agg.organisation_id = am.organisation_id
                AND b_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli_agg.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
            ORDER BY am.reporting_category, am.account_code
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "rows": [dict(r) for r in rows],
    }


# ──────────────────────────────────────────────────────────────────────
# HELPERS: Default period and YYYY-MM list
# ──────────────────────────────────────────────────────────────────────

def _default_period_start() -> date:
    """1 April of current FY (April start)."""
    today = date.today()
    fy_year = today.year if today.month >= FY_START_MONTH else today.year - 1
    return date(fy_year, FY_START_MONTH, 1)


def _months_yyyy_mm_in_range(period_start: date, period_end: date) -> list[str]:
    """Return list of YYYY-MM strings for every month in [period_start, period_end]."""
    out: list[str] = []
    y, m = period_start.year, period_start.month
    while (y, m) <= (period_end.year, period_end.month):
        out.append(f"{y}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


# OpEx reporting categories (P&L) for EBITDA calculation
_OPEX_CATEGORIES = frozenset({
    "Payroll & People Costs",
    "Marketing & Sales",
    "Technology & Infrastructure",
    "Professional Fees",
    "General & Administrative",
})


# ──────────────────────────────────────────────────────────────────────
# ACTUAL VS BUDGET - KPIs
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/avb-kpis")
async def avb_kpis(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Pre-calculated AvB KPIs. organisation_id from JWT only.
    Optional period_start (default: 1 April current FY), period_end (default: today).
    Actuals from financial_line_items + account_mappings (natural_sign applied);
    budget from budget_monthly. All calculations backend-only; divide-by-zero returns 0.0.
    """
    org_id = str(current_user.organisation_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    today = date.today()
    ps = period_start if period_start is not None else _default_period_start()
    pe = period_end if period_end is not None else today
    if ps > pe:
        ps, pe = pe, ps

    periods_list = _months_yyyy_mm_in_range(ps, pe)

    # Actuals by reporting_category (P&L only; natural_sign applied)
    actuals_result = await db.execute(
        text("""
            SELECT
                am.reporting_category,
                SUM(fli.net_amount * am.natural_sign) AS actual
            FROM financial_line_items fli
            JOIN account_mappings am
                ON  am.organisation_id = fli.organisation_id
                AND am.xero_account_id = fli.xero_account_id
            WHERE fli.organisation_id = :org_id
              AND fli.report_type = 'ProfitAndLoss'
              AND fli.period_start >= :period_start
              AND fli.period_end   <= :period_end
              AND am.statement_type = 'profit_and_loss'
            GROUP BY am.reporting_category
        """),
        {"org_id": org_id, "period_start": ps, "period_end": pe},
    )
    actuals_by_cat = {r["reporting_category"]: float(r["actual"] or 0) for r in actuals_result.mappings().all()}

    # Budget by reporting_category from budget_monthly (join to account_mappings for category)
    if not periods_list:
        budget_by_cat = {}
    else:
        budget_stmt = text("""
            SELECT am.reporting_category, SUM(b.budget_amount) AS budget
            FROM budget_monthly b
            JOIN account_mappings am
                ON  am.organisation_id = b.organisation_id
                AND am.account_code    = b.account_code
            WHERE b.organisation_id = :org_id
              AND b.period IN :periods
              AND am.statement_type = 'profit_and_loss'
            GROUP BY am.reporting_category
        """).bindparams(bindparam("periods", expanding=True))
        budget_result = await db.execute(budget_stmt, {"org_id": org_id, "periods": periods_list})
        budget_by_cat = {r["reporting_category"]: float(r["budget"] or 0) for r in budget_result.mappings().all()}

    def _act(cat: str) -> float:
        return actuals_by_cat.get(cat, 0.0)

    def _bud(cat: str) -> float:
        return budget_by_cat.get(cat, 0.0)

    revenue_actual_ytd = _act("Revenue")
    revenue_budget_ytd = _bud("Revenue")
    cost_of_sales_actual = _act("Cost of Sales")
    cost_of_sales_budget = _bud("Cost of Sales")

    revenue_variance = revenue_actual_ytd - revenue_budget_ytd
    revenue_variance_pct = (
        (revenue_variance / abs(revenue_budget_ytd) * 100) if revenue_budget_ytd != 0 else 0.0
    )

    gross_profit_actual = revenue_actual_ytd - cost_of_sales_actual
    gross_profit_budget = revenue_budget_ytd - cost_of_sales_budget
    gross_margin_actual_pct = (
        (gross_profit_actual / revenue_actual_ytd * 100) if revenue_actual_ytd != 0 else 0.0
    )
    gross_margin_budget_pct = (
        (gross_profit_budget / revenue_budget_ytd * 100) if revenue_budget_ytd != 0 else 0.0
    )
    gross_margin_variance_pct = gross_margin_actual_pct - gross_margin_budget_pct

    opex_actual = sum(_act(c) for c in _OPEX_CATEGORIES)
    opex_budget = -sum(_bud(c) for c in _OPEX_CATEGORIES)
    ebitda_actual = gross_profit_actual + opex_actual
    ebitda_budget = gross_profit_budget + opex_budget
    ebitda_variance = ebitda_actual - ebitda_budget
    ebitda_variance_pct = (
        (ebitda_variance / abs(ebitda_budget) * 100) if ebitda_budget != 0 else 0.0
    )

    budget_achievement_pct = (
        (revenue_actual_ytd / revenue_budget_ytd * 100) if revenue_budget_ytd != 0 else 0.0
    )

    cost_ratio_actual = (
        (abs(opex_actual) / revenue_actual_ytd * 100) if revenue_actual_ytd != 0 else 0.0
    )
    cost_ratio_budget = (
        (abs(opex_budget) / revenue_budget_ytd * 100) if revenue_budget_ytd != 0 else 0.0
    )

    # Balance sheet data not yet in financial_line_items
    cash_position = 0.0
    debtor_days = 0

    days_in_period = max(1, (pe - ps).days + 1)

    return {
        "period_start": str(ps),
        "period_end": str(pe),
        "revenue_actual_ytd": round(revenue_actual_ytd, 2),
        "revenue_budget_ytd": round(revenue_budget_ytd, 2),
        "revenue_variance": round(revenue_variance, 2),
        "revenue_variance_pct": round(revenue_variance_pct, 2),
        "gross_profit_actual": round(gross_profit_actual, 2),
        "gross_profit_budget": round(gross_profit_budget, 2),
        "gross_margin_actual_pct": round(gross_margin_actual_pct, 2),
        "gross_margin_budget_pct": round(gross_margin_budget_pct, 2),
        "gross_margin_variance_pct": round(gross_margin_variance_pct, 2),
        "ebitda_actual": round(ebitda_actual, 2),
        "ebitda_budget": round(ebitda_budget, 2),
        "ebitda_variance": round(ebitda_variance, 2),
        "ebitda_variance_pct": round(ebitda_variance_pct, 2),
        "budget_achievement_pct": round(budget_achievement_pct, 2),
        "opex_actual": round(opex_actual, 2),
        "opex_budget": round(opex_budget, 2),
        "cost_ratio_actual": round(cost_ratio_actual, 2),
        "cost_ratio_budget": round(cost_ratio_budget, 2),
        "cash_position": round(cash_position, 2),
        "debtor_days": int(debtor_days),
    }


# ──────────────────────────────────────────────────────────────────────
# ACTUAL VS BUDGET - EBITDA BRIDGE
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/avb-bridge")
async def avb_bridge(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EBITDA variance waterfall bridge."""
    org_id = str(current_user.organisation_id)

    result = await db.execute(
        text("""
            WITH fli_agg AS (
                SELECT
                    organisation_id,
                    xero_account_id,
                    SUM(net_amount) AS net_amount
                FROM financial_line_items
                WHERE organisation_id = :org_id
                  AND report_type     = 'ProfitAndLoss'
                  AND period_start   >= :period_start
                  AND period_end     <= :period_end
                GROUP BY organisation_id, xero_account_id
            ),
            bm_agg AS (
                SELECT organisation_id, account_code, SUM(budget_amount) AS total_budget
                FROM budget_monthly
                WHERE organisation_id = :org_id
                  AND period >= TO_CHAR(CAST(:period_start AS DATE), 'YYYY-MM')
                  AND period <= TO_CHAR(CAST(:period_end AS DATE), 'YYYY-MM')
                GROUP BY organisation_id, account_code
            )
            SELECT
                am.reporting_category,
                COALESCE(SUM(fli_agg.net_amount), 0)      AS actual,
                COALESCE(SUM(bm_agg.total_budget), 0)     AS budget
            FROM account_mappings am
            LEFT JOIN fli_agg
                ON  fli_agg.organisation_id = am.organisation_id
                AND fli_agg.xero_account_id = am.xero_account_id
            LEFT JOIN bm_agg
                ON  bm_agg.organisation_id = am.organisation_id
                AND bm_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli_agg.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
            GROUP BY am.reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = {r["reporting_category"]: r for r in result.mappings().all()}

    rev_actual = float(rows.get("REVENUE", {}).get("actual", 0))
    rev_budget = float(rows.get("REVENUE", {}).get("budget", 0))
    cogs_actual = float(rows.get("COGS", {}).get("actual", 0))
    cogs_budget = float(rows.get("COGS", {}).get("budget", 0))
    opex_actual = float(rows.get("OPEX", {}).get("actual", 0))
    opex_budget = float(rows.get("OPEX", {}).get("budget", 0))

    ebitda_budget = rev_budget - cogs_budget - opex_budget
    ebitda_actual = rev_actual - cogs_actual - opex_actual

    rev_impact = rev_actual - rev_budget
    cogs_impact = -(cogs_actual - cogs_budget)
    opex_impact = -(opex_actual - opex_budget)

    bridge = [
        {"name": "Budget EBITDA", "value": round(ebitda_budget, 2), "type": "base"},
        {"name": "Revenue", "value": round(rev_impact, 2), "type": "positive" if rev_impact >= 0 else "negative"},
        {"name": "Direct Costs", "value": round(cogs_impact, 2), "type": "positive" if cogs_impact >= 0 else "negative"},
        {"name": "Operating Expenses", "value": round(opex_impact, 2), "type": "positive" if opex_impact >= 0 else "negative"},
        {"name": "Actual EBITDA", "value": round(ebitda_actual, 2), "type": "total"},
    ]

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "bridge": bridge,
    }


# ──────────────────────────────────────────────────────────────────────
# ACTUAL VS BUDGET - SUMMARY BY CATEGORY
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/avb-summary")
async def avb_summary(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Summary by reporting category (REVENUE, COGS, OPEX)."""
    org_id = str(current_user.organisation_id)

    result = await db.execute(
        text("""
            WITH fli_agg AS (
                SELECT
                    organisation_id,
                    xero_account_id,
                    SUM(net_amount) AS net_amount
                FROM financial_line_items
                WHERE organisation_id = :org_id
                  AND report_type     = 'ProfitAndLoss'
                  AND period_start   >= :period_start
                  AND period_end     <= :period_end
                GROUP BY organisation_id, xero_account_id
            ),
            b_agg AS (
                SELECT organisation_id, account_code, SUM(amount) AS total_budget
                FROM budgets
                WHERE organisation_id = :org_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                GROUP BY organisation_id, account_code
            )
            SELECT
                am.reporting_category,
                COALESCE(SUM(fli_agg.net_amount), 0)           AS actual,
                COALESCE(SUM(b_agg.total_budget), 0)           AS budget,
                COALESCE(SUM(fli_agg.net_amount), 0)
                    - COALESCE(SUM(b_agg.total_budget), 0)     AS variance,
                CASE
                    WHEN COALESCE(SUM(b_agg.total_budget), 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(SUM(fli_agg.net_amount), 0) - COALESCE(SUM(b_agg.total_budget), 0))
                        / ABS(SUM(b_agg.total_budget)) * 100, 1
                    )
                END AS variance_pct
            FROM account_mappings am
            LEFT JOIN fli_agg
                ON  fli_agg.organisation_id = am.organisation_id
                AND fli_agg.xero_account_id = am.xero_account_id
            LEFT JOIN b_agg
                ON  b_agg.organisation_id = am.organisation_id
                AND b_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli_agg.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
            GROUP BY am.reporting_category
            ORDER BY am.reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "summary": [dict(r) for r in rows],
    }


# ──────────────────────────────────────────────────────────────────────
# MONTHLY TREND
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/trend")
async def monthly_trend(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Monthly trend data for trend chart."""
    org_id = str(current_user.organisation_id)

    result = await db.execute(
        text("""
            SELECT
                fli.period_start                          AS month,
                am.reporting_category,
                COALESCE(SUM(fli.net_amount), 0)         AS actual,
                COALESCE(SUM(bm.budget_amount), 0)       AS budget,
                COALESCE(SUM(fli.net_amount), 0)
                    - COALESCE(SUM(bm.budget_amount), 0) AS variance
            FROM financial_line_items fli
            JOIN account_mappings am
                ON  am.organisation_id = fli.organisation_id
                AND am.xero_account_id = fli.xero_account_id
            LEFT JOIN budget_monthly bm
                ON  bm.organisation_id = am.organisation_id
                AND bm.account_code    = am.account_code
                AND bm.period          = TO_CHAR(fli.period_start, 'YYYY-MM')
            WHERE fli.organisation_id = :org_id
              AND fli.report_type     = 'ProfitAndLoss'
              AND fli.period_start   >= :period_start
              AND fli.period_end     <= :period_end
              AND am.include_in_pnl   = TRUE
            GROUP BY fli.period_start, am.reporting_category
            ORDER BY fli.period_start, am.reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "trend": [dict(r) for r in rows],
    }


# ──────────────────────────────────────────────────────────────────────
# ACTUALS ONLY
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/actuals")
async def actuals(
    period_start: date,
    period_end: date,
    reporting_category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actuals by account for a given period."""
    org_id = str(current_user.organisation_id)

    query = """
        SELECT
            am.account_code,
            am.account_name,
            am.reporting_category,
            fli.period_start,
            fli.period_end,
            fli.net_amount AS actual
        FROM financial_line_items fli
        JOIN account_mappings am
            ON  am.organisation_id = fli.organisation_id
            AND am.xero_account_id = fli.xero_account_id
        WHERE fli.organisation_id = :org_id
          AND fli.report_type     = 'ProfitAndLoss'
          AND fli.period_start   >= :period_start
          AND fli.period_end     <= :period_end
    """
    params: dict = {
        "org_id": org_id,
        "period_start": period_start,
        "period_end": period_end,
    }

    if reporting_category:
        query += " AND am.reporting_category = :reporting_category"
        params["reporting_category"] = reporting_category

    query += " ORDER BY fli.period_start, am.reporting_category, am.account_code"

    result = await db.execute(text(query), params)
    rows = result.mappings().all()

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "rows": [dict(r) for r in rows],
    }


# ──────────────────────────────────────────────────────────────────────
# DATA HEALTH
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/data-health")
async def data_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Data health summary for the Data Health dashboard page.
    Returns mapping coverage, budget coverage, and data completeness.
    Handles xero_connections schema differences safely.
    """
    org_id = str(current_user.organisation_id)

    # Mapping coverage
    mapping_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_mapped = TRUE) AS mapped,
                COUNT(*) FILTER (
                    WHERE is_mapped = FALSE
                       OR reporting_category IS NULL
                       OR reporting_category = ''
                ) AS unmapped
            FROM account_mappings
            WHERE organisation_id = :org_id
        """),
        {"org_id": org_id},
    )
    mapping_row = dict(mapping_result.mappings().fetchone() or {})

    # Budget coverage
    budget_result = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT am.account_code) AS pnl_accounts,
                COUNT(DISTINCT b.account_code)  AS accounts_with_budget
            FROM account_mappings am
            LEFT JOIN budget_monthly b
                ON  b.organisation_id = am.organisation_id
                AND b.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.statement_type  = 'profit_and_loss'
              AND am.is_mapped       = TRUE
        """),
        {"org_id": org_id},
    )
    budget_row = dict(budget_result.mappings().fetchone() or {})

    # Data completeness
    period_result = await db.execute(
        text("""
            SELECT
                COUNT(DISTINCT period_start) AS periods_with_data,
                MIN(period_start)            AS earliest_period,
                MAX(period_end)              AS latest_period,
                COUNT(*)                     AS total_line_items
            FROM financial_line_items
            WHERE organisation_id = :org_id
              AND report_type = 'ProfitAndLoss'
        """),
        {"org_id": org_id},
    )
    period_row = dict(period_result.mappings().fetchone() or {})

    # Xero connection status
    xero_columns_result = await db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'xero_connections'
        """)
    )
    xero_columns = {row["column_name"] for row in xero_columns_result.mappings().all()}

    name_candidates = ["tenant_name", "tenant_display_name", "xero_tenant_name", "organisation_name", "company_name", "name"]
    connected_candidates = ["connected_at", "created_at", "updated_at", "last_synced_at", "last_sync_at"]
    expiry_candidates = ["token_expiry", "expires_at", "access_token_expires_at", "expiry_at"]
    order_candidates = ["connected_at", "updated_at", "created_at", "last_synced_at", "last_sync_at"]

    name_col = next((c for c in name_candidates if c in xero_columns), None)
    connected_col = next((c for c in connected_candidates if c in xero_columns), None)
    expiry_col = next((c for c in expiry_candidates if c in xero_columns), None)
    order_col = next((c for c in order_candidates if c in xero_columns), None)

    xero_status = None

    if xero_columns:
        select_parts = []
        if name_col:
            select_parts.append(f"{name_col} AS tenant_name")
        if connected_col:
            select_parts.append(f"{connected_col} AS connected_at")
        if expiry_col:
            select_parts.append(f"{expiry_col} AS token_expiry")

        if not select_parts:
            xero_query = "SELECT organisation_id FROM xero_connections WHERE organisation_id = :org_id LIMIT 1"
            xero_result = await db.execute(text(xero_query), {"org_id": org_id})
            xero_row = xero_result.mappings().fetchone()
            if xero_row:
                xero_status = {"tenant_name": None, "connected_at": None, "token_expiry": None, "connected": True}
        else:
            order_clause = f" ORDER BY {order_col} DESC" if order_col else ""
            xero_query = f"""
                SELECT {", ".join(select_parts)}
                FROM xero_connections
                WHERE organisation_id = :org_id
                {order_clause}
                LIMIT 1
            """
            xero_result = await db.execute(text(xero_query), {"org_id": org_id})
            xero_row = xero_result.mappings().fetchone()
            if xero_row:
                xero_status = {
                    "tenant_name": xero_row.get("tenant_name"),
                    "connected_at": str(xero_row.get("connected_at")) if xero_row.get("connected_at") else None,
                    "token_expiry": str(xero_row.get("token_expiry")) if xero_row.get("token_expiry") else None,
                    "connected": True,
                }

    mapping_total = int(mapping_row.get("total") or 0)
    mapping_mapped = int(mapping_row.get("mapped") or 0)
    budget_pnl_accounts = int(budget_row.get("pnl_accounts") or 0)
    budget_accounts_with_budget = int(budget_row.get("accounts_with_budget") or 0)

    mapping_coverage_pct = round((mapping_mapped / mapping_total) * 100, 1) if mapping_total else 0.0
    budget_coverage_pct = round((budget_accounts_with_budget / budget_pnl_accounts) * 100, 1) if budget_pnl_accounts else 0.0

    return {
        "mapping": {
            "total": mapping_total,
            "mapped": mapping_mapped,
            "unmapped": int(mapping_row.get("unmapped") or 0),
            "coverage_pct": mapping_coverage_pct,
        },
        "budget": {
            "pnl_accounts": budget_pnl_accounts,
            "accounts_with_budget": budget_accounts_with_budget,
            "coverage_pct": budget_coverage_pct,
        },
        "data": {
            "periods_with_data": int(period_row.get("periods_with_data") or 0),
            "earliest_period": str(period_row.get("earliest_period")) if period_row.get("earliest_period") else None,
            "latest_period": str(period_row.get("latest_period")) if period_row.get("latest_period") else None,
            "total_line_items": int(period_row.get("total_line_items") or 0),
        },
        "xero": xero_status,
    }
