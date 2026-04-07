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
from datetime import date, timedelta
import io
import csv

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.fiscal_year_service import (
    get_current_fy,
    get_fy_context,
    generate_fy_rows,
    ensure_fiscal_months_current,
    get_last_closed_period_end_date,
)
from app.services.budget_service import (
    get_budget_status,
    get_budget_source,
    fy_periods_for_range,
)

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


async def _get_fy_start_month(db: AsyncSession, org_id: str) -> int:
    """Fetch fy_start_month from the organisations table for the given org."""
    result = await db.execute(
        text("SELECT fy_start_month FROM organisations WHERE id = :org_id"),
        {"org_id": org_id},
    )
    row = result.scalar()
    return int(row) if row is not None else 4


def _fy_bounds_for_period(period_start: date, fy_start_month: int) -> tuple:
    """Return (fy_start, fy_end) for the FY containing period_start."""
    if period_start.month >= fy_start_month:
        fy_year = period_start.year
    else:
        fy_year = period_start.year - 1
    fy_start = date(fy_year, fy_start_month, 1)
    fy_end = date(fy_year + 1, fy_start_month, 1) - timedelta(days=1)
    return fy_start, fy_end


def _period_for_fy_month(fiscal_year: int, month_name: str, fy_start_month: int) -> str:
    """Return YYYY-MM for the given FY year and month column (apr..mar)."""
    month_num = _MONTH_NAME_TO_NUM[month_name.lower()]
    if month_num >= fy_start_month:
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
    org_id = str(current_user.active_org_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    # Default fiscal year: use org's fy_start_month
    fy_start_month = await _get_fy_start_month(db, org_id)
    today = date.today()
    if fiscal_year is None:
        fiscal_year = today.year if today.month >= fy_start_month else today.year - 1

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
            period = _period_for_fy_month(fiscal_year, month_col, fy_start_month)
            total_budget_loaded += amount
            await db.execute(
                text("""
                    INSERT INTO budget_monthly
                        (organisation_id, account_code, account_name, reporting_category, period, budget_amount, source, updated_at)
                    VALUES
                        (:org_id, :account_code, :account_name, :reporting_category, :period, :budget_amount, 'csv_upload', now())
                    ON CONFLICT (organisation_id, account_code, period)
                    DO UPDATE SET
                        account_name = EXCLUDED.account_name,
                        reporting_category = EXCLUDED.reporting_category,
                        budget_amount = EXCLUDED.budget_amount,
                        source = EXCLUDED.source,
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
# COMPLETED PERIODS (fiscal_year_months.is_completed)
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/completed-periods")
async def get_completed_periods(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List months marked completed (auto or manual) for Period Close / Settings UI.
    month_period is normalised as YYYY-MM via substring — never cast to ::date.
    """
    org_id = str(current_user.active_org_id)
    if not org_id or org_id == "None":
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    await ensure_fiscal_months_current(db, org_id)

    fy_cur = await db.execute(
        text(
            "SELECT fy_year, fy_label FROM fiscal_years "
            "WHERE organisation_id = :org_id AND is_current = true LIMIT 1"
        ),
        {"org_id": org_id},
    )
    fy_cur_row = fy_cur.mappings().first()
    if fy_cur_row:
        current_fy_year = int(fy_cur_row["fy_year"])
        current_fy_label = str(fy_cur_row["fy_label"])
    else:
        fy_fallback = await get_current_fy(db, org_id)
        current_fy_year = int(fy_fallback["fy_year"])
        current_fy_label = str(fy_fallback["fy_label"])

    mp_key = "substring(trim(month_period::text) from 1 for 7)"

    list_result = await db.execute(
        text(
            f"""
            SELECT fy_year, month_number, {mp_key} AS month_period
            FROM fiscal_year_months
            WHERE organisation_id = :org_id AND is_completed = true
            ORDER BY {mp_key} ASC
            """
        ),
        {"org_id": org_id},
    )
    rows = list_result.mappings().all()
    completed_periods = []
    for r in rows:
        mp = (r["month_period"] or "").strip()
        if len(mp) >= 7:
            mp = mp[:7]
        else:
            continue
        fy_year = r["fy_year"]
        fy_label = f"FY{fy_year % 100:02d}"
        completed_periods.append(
            {
                "month_period": mp,
                "fy_label": fy_label,
                "month_number": int(r["month_number"] or 0),
            }
        )

    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)::int AS n
            FROM fiscal_year_months
            WHERE organisation_id = :org_id
              AND fy_year = :fy_year
              AND is_completed = true
            """
        ),
        {"org_id": org_id, "fy_year": current_fy_year},
    )
    cr = count_result.mappings().first()
    total_completed_current_fy = int(cr["n"]) if cr and cr.get("n") is not None else 0

    latest_result = await db.execute(
        text(
            f"""
            SELECT {mp_key} AS mp
            FROM fiscal_year_months
            WHERE organisation_id = :org_id
              AND fy_year = :fy_year
              AND is_completed = true
            ORDER BY {mp_key} DESC
            LIMIT 1
            """
        ),
        {"org_id": org_id, "fy_year": current_fy_year},
    )
    lr = latest_result.mappings().first()
    latest_completed = None
    if lr and lr["mp"]:
        s = (lr["mp"] or "").strip()
        latest_completed = s[:7] if len(s) >= 7 else None

    next_result = await db.execute(
        text(
            f"""
            SELECT {mp_key} AS mp
            FROM fiscal_year_months
            WHERE organisation_id = :org_id AND is_completed = false
            ORDER BY {mp_key} ASC
            LIMIT 1
            """
        ),
        {"org_id": org_id},
    )
    nr = next_result.mappings().first()
    next_to_complete = None
    if nr and nr["mp"]:
        s = (nr["mp"] or "").strip()
        next_to_complete = s[:7] if len(s) >= 7 else None

    return {
        "completed_periods": completed_periods,
        "latest_completed": latest_completed,
        "total_completed": total_completed_current_fy,
        "current_fy_label": current_fy_label,
        "next_to_complete": next_to_complete,
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
    org_id = str(current_user.active_org_id)

    result = await db.execute(
        text("""
            WITH fli_agg AS (
                SELECT
                    fli.organisation_id,
                    fli.xero_account_id,
                    SUM(fli.net_amount) AS net_amount
                FROM financial_line_items fli
                JOIN account_mappings am
                    ON  am.organisation_id = fli.organisation_id
                    AND am.xero_account_id = fli.xero_account_id
                WHERE fli.organisation_id = :org_id
                  AND fli.report_type     = 'ProfitAndLoss'
                  AND fli.period_start   >= :period_start
                  AND fli.period_end     <= :period_end
                  AND am.statement_type   = 'profit_and_loss'
                GROUP BY fli.organisation_id, fli.xero_account_id
            ),
            bm_agg AS (
                -- Pre-aggregate budgets to one row per account_code
                -- across the full requested period (YYYY-MM matching).
                SELECT organisation_id, account_code, SUM(budget_amount) AS total_budget
                FROM budget_monthly
                WHERE organisation_id = :org_id
                  AND period >= TO_CHAR(CAST(:period_start AS DATE), 'YYYY-MM')
                  AND period <= TO_CHAR(CAST(:period_end AS DATE), 'YYYY-MM')
                GROUP BY organisation_id, account_code
            )
            SELECT
                am.reporting_category,
                am.account_code,
                am.account_name,
                COALESCE(fli_agg.net_amount, 0)            AS actual,
                COALESCE(bm_agg.total_budget, 0)           AS budget,
                COALESCE(fli_agg.net_amount, 0)
                    - COALESCE(bm_agg.total_budget, 0)     AS variance,
                CASE
                    WHEN COALESCE(bm_agg.total_budget, 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(fli_agg.net_amount, 0) - COALESCE(bm_agg.total_budget, 0))
                        / ABS(bm_agg.total_budget) * 100, 1
                    )
                END AS variance_pct
            FROM account_mappings am
            LEFT JOIN fli_agg
                ON  fli_agg.organisation_id = am.organisation_id
                AND fli_agg.xero_account_id = am.xero_account_id
            LEFT JOIN bm_agg
                ON  bm_agg.organisation_id = am.organisation_id
                AND bm_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND am.statement_type  = 'profit_and_loss'
              AND (fli_agg.net_amount IS NOT NULL OR bm_agg.total_budget IS NOT NULL)
            ORDER BY am.reporting_category, am.account_code
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()

    fy_start_month = await _get_fy_start_month(db, org_id)
    fy_s, fy_e = _fy_bounds_for_period(period_start, fy_start_month)
    fy_periods = fy_periods_for_range(fy_s, fy_e)
    budget_status = await get_budget_status(db, org_id, fy_s, fy_e)
    budget_source = await get_budget_source(db, org_id, fy_periods)

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "rows": [dict(r) for r in rows],
        "budget_status": budget_status,
        "budget_source": budget_source,
    }


# ──────────────────────────────────────────────────────────────────────
# HELPERS: Default period and YYYY-MM list
# ──────────────────────────────────────────────────────────────────────

def _default_period_start(fy_start_month: int) -> date:
    """1st of fy_start_month in the current FY."""
    today = date.today()
    fy_year = today.year if today.month >= fy_start_month else today.year - 1
    return date(fy_year, fy_start_month, 1)


def _calendar_last_completed_month_end() -> date:
    """Last day of the calendar month immediately before the current month."""
    today = date.today()
    first_of_month = today.replace(day=1)
    return first_of_month - timedelta(days=1)


async def _resolve_default_period_end(db: AsyncSession, org_id: str) -> date:
    """Return fallback report period end when the client does not pass period params.

    Default behaviour is latest closed fiscal month, else the last completed
    calendar month. Frontend flows should pass explicit period_start and
    period_end whenever a user has selected a specific FY or wants to include
    in-progress month data; this backend default is only for omitted params.
    """
    last_closed = await get_last_closed_period_end_date(db, org_id)
    if last_closed is not None:
        return last_closed
    return _calendar_last_completed_month_end()


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
    Optional period_start (default: 1 April current FY), period_end (default: latest closed
    fiscal month, else last day of the previous completed calendar month).
    Actuals from financial_line_items + account_mappings (natural_sign applied);
    budget from budget_monthly. All calculations backend-only; divide-by-zero returns 0.0.
    """
    org_id = str(current_user.active_org_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    fy_start_month = await _get_fy_start_month(db, org_id)
    ps = period_start if period_start is not None else _default_period_start(fy_start_month)
    pe = period_end if period_end is not None else await _resolve_default_period_end(db, org_id)
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

    gross_profit_actual = revenue_actual_ytd + cost_of_sales_actual
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

    # Cash position from Balance Sheet (BANK accounts, most recent period)
    cash_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(fli.net_amount), 0) AS cash
            FROM financial_line_items fli
            JOIN account_mappings am
              ON fli.organisation_id = am.organisation_id
              AND fli.xero_account_id = am.xero_account_id
            WHERE fli.organisation_id = :org_id
              AND fli.report_type = 'BalanceSheet'
              AND am.reporting_category = 'Cash & Bank'
              AND fli.period_end = (
                SELECT MAX(period_end)
                FROM financial_line_items
                WHERE organisation_id = :org_id
                  AND report_type = 'BalanceSheet'
                  AND period_end <= :period_end
              )
        """),
        {"org_id": org_id, "period_end": pe},
    )
    cash_position = float((cash_result.scalar() or 0))

    # Debtor days from Balance Sheet (receivable accounts in CURRENT_ASSET)
    ar_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(fli.net_amount), 0) AS ar
            FROM financial_line_items fli
            JOIN account_mappings am
              ON fli.organisation_id = am.organisation_id
              AND fli.xero_account_id = am.xero_account_id
            WHERE fli.organisation_id = :org_id
              AND fli.report_type = 'BalanceSheet'
              AND am.reporting_category = 'Current Assets'
              AND LOWER(am.account_name) LIKE '%%receivable%%'
              AND fli.period_end = (
                SELECT MAX(period_end)
                FROM financial_line_items
                WHERE organisation_id = :org_id
                  AND report_type = 'BalanceSheet'
                  AND period_end <= :period_end
              )
        """),
        {"org_id": org_id, "period_end": pe},
    )
    accounts_receivable = float((ar_result.scalar() or 0))

    days_in_period = max(1, (pe - ps).days + 1)
    debtor_days = (
        (accounts_receivable / revenue_actual_ytd) * days_in_period
        if revenue_actual_ytd != 0 else 0
    )

    fy_s, fy_e = _fy_bounds_for_period(ps, fy_start_month)
    fy_periods = fy_periods_for_range(fy_s, fy_e)
    budget_status = await get_budget_status(db, org_id, fy_s, fy_e)
    budget_source = await get_budget_source(db, org_id, fy_periods)

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
        "budget_status": budget_status,
        "budget_source": budget_source,
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
    org_id = str(current_user.active_org_id)

    result = await db.execute(
        text("""
            WITH fli_agg AS (
                SELECT
                    fli.organisation_id,
                    fli.xero_account_id,
                    SUM(fli.net_amount) AS net_amount
                FROM financial_line_items fli
                JOIN account_mappings am
                    ON  am.organisation_id = fli.organisation_id
                    AND am.xero_account_id = fli.xero_account_id
                WHERE fli.organisation_id = :org_id
                  AND fli.report_type     = 'ProfitAndLoss'
                  AND fli.period_start   >= :period_start
                  AND fli.period_end     <= :period_end
                  AND am.statement_type   = 'profit_and_loss'
                GROUP BY fli.organisation_id, fli.xero_account_id
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
              AND am.statement_type  = 'profit_and_loss'
              AND (fli_agg.net_amount IS NOT NULL OR bm_agg.total_budget IS NOT NULL)
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

    fy_start_month = await _get_fy_start_month(db, org_id)
    fy_s, fy_e = _fy_bounds_for_period(period_start, fy_start_month)
    fy_periods = fy_periods_for_range(fy_s, fy_e)
    budget_status = await get_budget_status(db, org_id, fy_s, fy_e)
    budget_source = await get_budget_source(db, org_id, fy_periods)

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "bridge": bridge,
        "budget_status": budget_status,
        "budget_source": budget_source,
    }


# ──────────────────────────────────────────────────────────────────────
# ACTUAL VS BUDGET - SUMMARY BY CATEGORY
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/avb-summary")
async def avb_summary(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Summary by reporting category (REVENUE, COGS, OPEX)."""
    org_id = str(current_user.active_org_id)
    fy_start_month = await _get_fy_start_month(db, org_id)
    ps = period_start if period_start is not None else _default_period_start(fy_start_month)
    pe = period_end if period_end is not None else await _resolve_default_period_end(db, org_id)
    if ps > pe:
        ps, pe = pe, ps
    period_start, period_end = ps, pe

    result = await db.execute(
        text("""
            WITH fli_agg AS (
                SELECT
                    fli.organisation_id,
                    fli.xero_account_id,
                    SUM(fli.net_amount) AS net_amount
                FROM financial_line_items fli
                JOIN account_mappings am
                    ON  am.organisation_id = fli.organisation_id
                    AND am.xero_account_id = fli.xero_account_id
                WHERE fli.organisation_id = :org_id
                  AND fli.report_type     = 'ProfitAndLoss'
                  AND fli.period_start   >= :period_start
                  AND fli.period_end     <= :period_end
                  AND am.statement_type   = 'profit_and_loss'
                GROUP BY fli.organisation_id, fli.xero_account_id
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
                COALESCE(SUM(fli_agg.net_amount), 0)            AS actual,
                COALESCE(SUM(bm_agg.total_budget), 0)           AS budget,
                COALESCE(SUM(fli_agg.net_amount), 0)
                    - COALESCE(SUM(bm_agg.total_budget), 0)     AS variance,
                CASE
                    WHEN COALESCE(SUM(bm_agg.total_budget), 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(SUM(fli_agg.net_amount), 0) - COALESCE(SUM(bm_agg.total_budget), 0))
                        / ABS(SUM(bm_agg.total_budget)) * 100, 1
                    )
                END AS variance_pct
            FROM account_mappings am
            LEFT JOIN fli_agg
                ON  fli_agg.organisation_id = am.organisation_id
                AND fli_agg.xero_account_id = am.xero_account_id
            LEFT JOIN bm_agg
                ON  bm_agg.organisation_id = am.organisation_id
                AND bm_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND am.statement_type  = 'profit_and_loss'
              AND (fli_agg.net_amount IS NOT NULL OR bm_agg.total_budget IS NOT NULL)
            GROUP BY am.reporting_category
            ORDER BY am.reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()

    fy_s, fy_e = _fy_bounds_for_period(period_start, fy_start_month)
    fy_periods = fy_periods_for_range(fy_s, fy_e)
    budget_status = await get_budget_status(db, org_id, fy_s, fy_e)
    budget_source = await get_budget_source(db, org_id, fy_periods)

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "summary": [dict(r) for r in rows],
        "budget_status": budget_status,
        "budget_source": budget_source,
    }


# ──────────────────────────────────────────────────────────────────────
# MONTHLY TREND
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/trend")
async def monthly_trend(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Monthly trend data for trend chart."""
    org_id = str(current_user.active_org_id)
    fy_start_month = await _get_fy_start_month(db, org_id)
    ps = period_start if period_start is not None else _default_period_start(fy_start_month)
    pe = period_end if period_end is not None else await _resolve_default_period_end(db, org_id)
    if ps > pe:
        ps, pe = pe, ps
    period_start, period_end = ps, pe

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
              AND am.statement_type   = 'profit_and_loss'
            GROUP BY fli.period_start, am.reporting_category
            ORDER BY fli.period_start, am.reporting_category
        """),
        {"org_id": org_id, "period_start": period_start, "period_end": period_end},
    )
    rows = result.mappings().all()

    fy_s, fy_e = _fy_bounds_for_period(period_start, fy_start_month)
    fy_periods = fy_periods_for_range(fy_s, fy_e)
    budget_status = await get_budget_status(db, org_id, fy_s, fy_e)
    budget_source = await get_budget_source(db, org_id, fy_periods)

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "trend": [dict(r) for r in rows],
        "budget_status": budget_status,
        "budget_source": budget_source,
    }


# ──────────────────────────────────────────────────────────────────────
# ACTUALS ONLY
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/actuals")
async def actuals(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    reporting_category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actuals by account for a given period."""
    org_id = str(current_user.active_org_id)
    fy_start_month = await _get_fy_start_month(db, org_id)
    ps = period_start if period_start is not None else _default_period_start(fy_start_month)
    pe = period_end if period_end is not None else await _resolve_default_period_end(db, org_id)
    if ps > pe:
        ps, pe = pe, ps
    period_start, period_end = ps, pe

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
          AND am.statement_type  = 'profit_and_loss'
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
    org_id = str(current_user.active_org_id)

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
            xero_query = "SELECT organisation_id FROM xero_connections WHERE organisation_id = :org_id AND is_active = true LIMIT 1"
            xero_result = await db.execute(text(xero_query), {"org_id": org_id})
            xero_row = xero_result.mappings().fetchone()
            if xero_row:
                xero_status = {"tenant_name": None, "connected_at": None, "token_expiry": None, "connected": True}
        else:
            order_clause = f" ORDER BY {order_col} DESC" if order_col else ""
            xero_query = f"""
                SELECT {", ".join(select_parts)}
                FROM xero_connections
                WHERE organisation_id = :org_id AND is_active = true
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


# ──────────────────────────────────────────────────────────────────────
# BALANCE SHEET
# ──────────────────────────────────────────────────────────────────────

# Section → categories mapping
_BS_SECTIONS = [
    {
        "name": "Assets",
        "categories": [
            {"key": "Current Assets", "label": "Current Assets"},
            {"key": "Fixed Assets", "label": "Fixed Assets"},
            {"key": "Cash & Bank", "label": "Cash & Bank"},
        ],
    },
    {
        "name": "Liabilities",
        "categories": [
            {"key": "Current Liabilities", "label": "Current Liabilities"},
            {"key": "Long-term Liabilities", "label": "Long-term Liabilities"},
        ],
    },
    {
        "name": "Equity",
        "categories": [
            {"key": "Equity", "label": "Equity"},
        ],
    },
]


@router.get("/reports/balance-sheet")
async def balance_sheet(
    as_of_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Balance Sheet report as of a given date.
    Default as_of_date = latest closed fiscal month end, else last day of previous calendar month.
    """
    org_id = str(current_user.active_org_id)

    if as_of_date:
        aod = date.fromisoformat(as_of_date)
    else:
        aod = await _resolve_default_period_end(db, org_id)

    # Prior month: last day of the month immediately before as_of_date
    prior_first = aod.replace(day=1)
    prior_month_date = prior_first - timedelta(days=1)

    bs_query = text("""
        SELECT
            am.reporting_category,
            am.account_code,
            am.account_name,
            fli.net_amount AS balance
        FROM financial_line_items fli
        JOIN account_mappings am
          ON fli.organisation_id = am.organisation_id
          AND fli.xero_account_id = am.xero_account_id
        WHERE fli.organisation_id = :org_id
          AND fli.report_type = 'BalanceSheet'
          AND fli.period_end = (
            SELECT MAX(period_end)
            FROM financial_line_items
            WHERE organisation_id = :org_id
              AND report_type = 'BalanceSheet'
              AND period_end <= :as_of_date
          )
        ORDER BY am.reporting_category, am.account_name
    """)

    # Fetch current and prior month data
    current_result = await db.execute(bs_query, {"org_id": org_id, "as_of_date": aod})
    current_rows = current_result.mappings().all()

    prior_result = await db.execute(bs_query, {"org_id": org_id, "as_of_date": prior_month_date})
    prior_rows = prior_result.mappings().all()

    # Build balance dicts keyed by (reporting_category, account_code)
    current_balances: dict[str, float] = {}
    prior_balances: dict[str, float] = {}

    # Group current rows by reporting_category
    accounts_by_cat: dict[str, list[dict]] = {}
    for row in current_rows:
        cat = row["reporting_category"]
        code = row["account_code"] or ""
        bal = round(float(row["balance"] or 0), 2)
        current_balances[code] = bal
        accounts_by_cat.setdefault(cat, []).append({
            "account_code": code,
            "account_name": row["account_name"] or "",
            "balance": bal,
        })

    for row in prior_rows:
        code = row["account_code"] or ""
        prior_balances[code] = round(float(row["balance"] or 0), 2)

    # Build sections with current, prior, and movement
    sections = []
    total_assets = 0.0
    total_liabilities = 0.0
    total_equity = 0.0
    prior_total_assets = 0.0
    prior_total_liabilities = 0.0
    prior_total_equity = 0.0

    for section_def in _BS_SECTIONS:
        categories = []
        section_total = 0.0
        section_prior_total = 0.0
        for cat_def in section_def["categories"]:
            cat_accounts = accounts_by_cat.get(cat_def["key"], [])
            cat_total = 0.0
            cat_prior_total = 0.0
            enriched_accounts = []
            for a in cat_accounts:
                prior_bal = prior_balances.get(a["account_code"], 0.0)
                movement = round(a["balance"] - prior_bal, 2)
                enriched_accounts.append({
                    **a,
                    "prior_balance": prior_bal,
                    "movement": movement,
                })
                cat_total += a["balance"]
                cat_prior_total += prior_bal
            cat_total = round(cat_total, 2)
            cat_prior_total = round(cat_prior_total, 2)
            section_total += cat_total
            section_prior_total += cat_prior_total
            categories.append({
                "category_key": cat_def["key"],
                "category_label": cat_def["label"],
                "accounts": enriched_accounts,
                "total": cat_total,
                "prior_total": cat_prior_total,
                "movement": round(cat_total - cat_prior_total, 2),
            })
        section_total = round(section_total, 2)
        section_prior_total = round(section_prior_total, 2)
        sections.append({
            "name": section_def["name"],
            "categories": categories,
            "total": section_total,
            "prior_total": section_prior_total,
            "movement": round(section_total - section_prior_total, 2),
        })
        if section_def["name"] == "Assets":
            total_assets = section_total
            prior_total_assets = section_prior_total
        elif section_def["name"] == "Liabilities":
            total_liabilities = section_total
            prior_total_liabilities = section_prior_total
        elif section_def["name"] == "Equity":
            total_equity = section_total
            prior_total_equity = section_prior_total

    return {
        "as_of_date": str(aod),
        "prior_as_of_date": str(prior_month_date),
        "sections": sections,
        "total_assets": round(total_assets, 2),
        "total_liabilities": round(total_liabilities, 2),
        "total_equity": round(total_equity, 2),
        "net_assets": round(total_assets - total_liabilities, 2),
        "prior_total_assets": round(prior_total_assets, 2),
        "prior_total_liabilities": round(prior_total_liabilities, 2),
        "prior_total_equity": round(prior_total_equity, 2),
        "movement_assets": round(total_assets - prior_total_assets, 2),
        "movement_liabilities": round(total_liabilities - prior_total_liabilities, 2),
        "movement_equity": round(total_equity - prior_total_equity, 2),
    }


# ──────────────────────────────────────────────────────────────────────
# REPORT SETTINGS (FY start month)
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/settings")
async def get_report_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return report settings for the current organisation."""
    org_id = str(current_user.active_org_id)
    fy_start_month = await _get_fy_start_month(db, org_id)
    return {"fy_start_month": fy_start_month}


@router.get("/reports/fy-context")
async def get_fy_context_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return fiscal year context for the current organisation."""
    org_id = str(current_user.active_org_id)
    await ensure_fiscal_months_current(db, org_id)
    return await get_fy_context(db, org_id)


@router.get("/reports/available-fys")
async def get_available_fys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return fiscal years for selector UI, including whether each FY has data."""
    org_id = str(current_user.active_org_id)
    if not org_id or org_id == "None":
        raise HTTPException(status_code=403, detail="Organisation not set for user")

    fy_start_month = await _get_fy_start_month(db, org_id)
    fy_result = await db.execute(
        text(
            """
            SELECT fy_year, fy_label, is_current
            FROM fiscal_years
            WHERE organisation_id = :org_id
            ORDER BY fy_year DESC
            """
        ),
        {"org_id": org_id},
    )
    fy_rows = fy_result.mappings().all()

    current_fy = await get_current_fy(db, org_id)
    current_fy_year = int(current_fy["fy_year"])

    fy_by_year: dict[int, dict] = {}
    for row in fy_rows:
        fy_year = int(row["fy_year"])
        if fy_year in fy_by_year:
            continue
        fy_by_year[fy_year] = {
            "fy_year": fy_year,
            "fy_label": str(row["fy_label"] or f"FY{fy_year % 100:02d}"),
            "is_current": bool(row["is_current"]),
        }

    if current_fy_year not in fy_by_year:
        fy_by_year[current_fy_year] = {
            "fy_year": current_fy_year,
            "fy_label": str(current_fy.get("fy_label") or f"FY{current_fy_year % 100:02d}"),
            "is_current": True,
        }

    financial_years = []
    for fy_year in sorted(fy_by_year.keys(), reverse=True):
        fy_start = date(fy_year, fy_start_month, 1)
        next_fy_start = date(fy_year + 1, fy_start_month, 1)
        fy_end = next_fy_start - timedelta(days=1)

        has_data_result = await db.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM financial_line_items
                    WHERE organisation_id = :org_id
                      AND period_start >= :fy_start
                      AND period_end <= :fy_end
                ) AS has_data
                """
            ),
            {"org_id": org_id, "fy_start": fy_start, "fy_end": fy_end},
        )
        has_data = bool(has_data_result.scalar())

        row = fy_by_year[fy_year]
        financial_years.append(
            {
                "fy_year": fy_year,
                "fy_label": row["fy_label"],
                "fy_start": fy_start.isoformat(),
                "fy_end": fy_end.isoformat(),
                "is_current": bool(row["is_current"] or fy_year == current_fy_year),
                "has_data": has_data,
            }
        )

    return {"financial_years": financial_years}


@router.patch("/reports/settings")
async def update_report_settings(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update report settings for the current organisation."""
    org_id = str(current_user.active_org_id)
    fy_start_month = payload.get("fy_start_month")
    if fy_start_month is None:
        raise HTTPException(status_code=422, detail="fy_start_month is required")
    if not isinstance(fy_start_month, int) or fy_start_month < 1 or fy_start_month > 12:
        raise HTTPException(status_code=422, detail="fy_start_month must be an integer between 1 and 12")
    await db.execute(
        text("UPDATE organisations SET fy_start_month = :fy_start_month WHERE id = :org_id"),
        {"fy_start_month": fy_start_month, "org_id": org_id},
    )
    await db.commit()
    await generate_fy_rows(db, org_id, fy_start_month)
    return {"fy_start_month": fy_start_month}
