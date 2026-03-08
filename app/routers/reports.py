"""
FinSight AI - Reports Router (Workstream 3)
============================================
Actual vs Budget reporting endpoints.
Queries financial_line_items (normalised) joined to account_mappings and budgets.
All financial calculations performed server-side.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from datetime import date

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


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
            SELECT
                am.reporting_category,
                am.account_code,
                am.account_name,
                COALESCE(fli.net_amount, 0)           AS actual,
                COALESCE(b_agg.total_budget, 0)       AS budget,
                COALESCE(fli.net_amount, 0)
                    - COALESCE(b_agg.total_budget, 0) AS variance,
                CASE
                    WHEN COALESCE(b_agg.total_budget, 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(fli.net_amount, 0) - COALESCE(b_agg.total_budget, 0))
                        / ABS(b_agg.total_budget) * 100, 1
                    )
                END AS variance_pct
            FROM account_mappings am
            LEFT JOIN financial_line_items fli
                ON  fli.organisation_id = am.organisation_id
                AND fli.xero_account_id = am.xero_account_id
                AND fli.report_type     = 'ProfitAndLoss'
                AND fli.period_start   >= :period_start
                AND fli.period_end     <= :period_end
            LEFT JOIN (
                SELECT organisation_id, account_code, SUM(amount) AS total_budget
                FROM budgets
                WHERE organisation_id = :org_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                GROUP BY organisation_id, account_code
            ) b_agg
                ON  b_agg.organisation_id = am.organisation_id
                AND b_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
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
# ACTUAL VS BUDGET - KPIs
# ──────────────────────────────────────────────────────────────────────

@router.get("/reports/avb-kpis")
async def avb_kpis(
    period_start: date,
    period_end: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Pre-calculated KPIs for the Actual vs Budget view.
    Returns Revenue, Gross Margin %, EBITDA, Monthly OpEx with budget variances.
    """
    org_id = str(current_user.organisation_id)

    result = await db.execute(
        text("""
            SELECT
                am.reporting_category,
                COALESCE(SUM(fli.net_amount), 0)      AS actual,
                COALESCE(SUM(b_agg.total_budget), 0)  AS budget
            FROM account_mappings am
            LEFT JOIN financial_line_items fli
                ON  fli.organisation_id = am.organisation_id
                AND fli.xero_account_id = am.xero_account_id
                AND fli.report_type     = 'ProfitAndLoss'
                AND fli.period_start   >= :period_start
                AND fli.period_end     <= :period_end
            LEFT JOIN (
                SELECT organisation_id, account_code, SUM(amount) AS total_budget
                FROM budgets
                WHERE organisation_id = :org_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                GROUP BY organisation_id, account_code
            ) b_agg
                ON  b_agg.organisation_id = am.organisation_id
                AND b_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
            GROUP BY am.reporting_category
            ORDER BY am.reporting_category
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

    ebitda_actual = rev_actual - cogs_actual - opex_actual
    ebitda_budget = rev_budget - cogs_budget - opex_budget

    gm_actual = rev_actual - cogs_actual
    gm_budget = rev_budget - cogs_budget
    gm_pct_actual = (gm_actual / rev_actual * 100) if rev_actual != 0 else 0
    gm_pct_budget = (gm_budget / rev_budget * 100) if rev_budget != 0 else 0

    months_in_period = max(
        1,
        (period_end.year - period_start.year) * 12 + period_end.month - period_start.month + 1
    )
    monthly_opex_actual = opex_actual / months_in_period
    monthly_opex_budget = opex_budget / months_in_period

    def safe_var_pct(actual_val: float, budget_val: float):
        if budget_val == 0:
            return None
        return round((actual_val - budget_val) / abs(budget_val) * 100, 1)

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "months_in_period": months_in_period,
        "kpis": {
            "revenue": {
                "actual": round(rev_actual, 2),
                "budget": round(rev_budget, 2),
                "variance": round(rev_actual - rev_budget, 2),
                "variance_pct": safe_var_pct(rev_actual, rev_budget),
            },
            "gross_margin": {
                "actual_pct": round(gm_pct_actual, 1),
                "budget_pct": round(gm_pct_budget, 1),
                "variance_bps": round((gm_pct_actual - gm_pct_budget) * 100, 0),
                "actual": round(gm_actual, 2),
                "budget": round(gm_budget, 2),
            },
            "ebitda": {
                "actual": round(ebitda_actual, 2),
                "budget": round(ebitda_budget, 2),
                "variance": round(ebitda_actual - ebitda_budget, 2),
                "variance_pct": safe_var_pct(ebitda_actual, ebitda_budget),
            },
            "monthly_opex": {
                "actual": round(monthly_opex_actual, 2),
                "budget": round(monthly_opex_budget, 2),
                "variance": round(monthly_opex_actual - monthly_opex_budget, 2),
                "variance_pct": safe_var_pct(monthly_opex_actual, monthly_opex_budget),
            },
        },
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
            SELECT
                am.reporting_category,
                COALESCE(SUM(fli.net_amount), 0)      AS actual,
                COALESCE(SUM(b_agg.total_budget), 0)  AS budget
            FROM account_mappings am
            LEFT JOIN financial_line_items fli
                ON  fli.organisation_id = am.organisation_id
                AND fli.xero_account_id = am.xero_account_id
                AND fli.report_type     = 'ProfitAndLoss'
                AND fli.period_start   >= :period_start
                AND fli.period_end     <= :period_end
            LEFT JOIN (
                SELECT organisation_id, account_code, SUM(amount) AS total_budget
                FROM budgets
                WHERE organisation_id = :org_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                GROUP BY organisation_id, account_code
            ) b_agg
                ON  b_agg.organisation_id = am.organisation_id
                AND b_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
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
            SELECT
                am.reporting_category,
                COALESCE(SUM(fli.net_amount), 0)      AS actual,
                COALESCE(SUM(b_agg.total_budget), 0)  AS budget,
                COALESCE(SUM(fli.net_amount), 0)
                    - COALESCE(SUM(b_agg.total_budget), 0) AS variance,
                CASE
                    WHEN COALESCE(SUM(b_agg.total_budget), 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(SUM(fli.net_amount), 0) - COALESCE(SUM(b_agg.total_budget), 0))
                        / ABS(SUM(b_agg.total_budget)) * 100, 1
                    )
                END AS variance_pct
            FROM account_mappings am
            LEFT JOIN financial_line_items fli
                ON  fli.organisation_id = am.organisation_id
                AND fli.xero_account_id = am.xero_account_id
                AND fli.report_type     = 'ProfitAndLoss'
                AND fli.period_start   >= :period_start
                AND fli.period_end     <= :period_end
            LEFT JOIN (
                SELECT organisation_id, account_code, SUM(amount) AS total_budget
                FROM budgets
                WHERE organisation_id = :org_id
                  AND period_start >= :period_start
                  AND period_end   <= :period_end
                GROUP BY organisation_id, account_code
            ) b_agg
                ON  b_agg.organisation_id = am.organisation_id
                AND b_agg.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
              AND (fli.net_amount IS NOT NULL OR b_agg.total_budget IS NOT NULL)
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
                COALESCE(SUM(b.amount), 0)               AS budget,
                COALESCE(SUM(fli.net_amount), 0)
                    - COALESCE(SUM(b.amount), 0)         AS variance
            FROM financial_line_items fli
            JOIN account_mappings am
                ON  am.organisation_id = fli.organisation_id
                AND am.xero_account_id = fli.xero_account_id
            LEFT JOIN budgets b
                ON  b.organisation_id = am.organisation_id
                AND b.account_code    = am.account_code
                AND b.period_start    = fli.period_start
                AND b.period_end      = fli.period_end
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
            LEFT JOIN budgets b
                ON  b.organisation_id = am.organisation_id
                AND b.account_code    = am.account_code
            WHERE am.organisation_id = :org_id
              AND am.include_in_pnl  = TRUE
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
    # Detect actual live schema instead of hardcoding columns like tenant_name
    xero_columns_result = await db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'xero_connections'
        """)
    )
    xero_columns = {row["column_name"] for row in xero_columns_result.mappings().all()}

    name_candidates = [
        "tenant_name",
        "tenant_display_name",
        "xero_tenant_name",
        "organisation_name",
        "company_name",
        "name",
    ]
    connected_candidates = [
        "connected_at",
        "created_at",
        "updated_at",
        "last_synced_at",
        "last_sync_at",
    ]
    expiry_candidates = [
        "token_expiry",
        "expires_at",
        "access_token_expires_at",
        "expiry_at",
    ]
    order_candidates = [
        "connected_at",
        "updated_at",
        "created_at",
        "last_synced_at",
        "last_sync_at",
    ]

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

        # If no recognised columns exist, just return basic connected flag
        if not select_parts:
            xero_query = """
                SELECT organisation_id
                FROM xero_connections
                WHERE organisation_id = :org_id
                LIMIT 1
            """
            xero_result = await db.execute(text(xero_query), {"org_id": org_id})
            xero_row = xero_result.mappings().fetchone()

            if xero_row:
                xero_status = {
                    "tenant_name": None,
                    "connected_at": None,
                    "token_expiry": None,
                    "connected": True,
                }
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
