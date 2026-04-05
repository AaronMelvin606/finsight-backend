"""
FinSight AI - Onboarding Service
=================================
Runs automatically after a customer connects their Xero account via OAuth.
Fetches Chart of Accounts, auto-maps accounts, generates fiscal year rows,
triggers an initial 24-month data sync, and marks onboarding complete.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone, timedelta, date
from dateutil.relativedelta import relativedelta
import httpx
import uuid
import json
import logging

from app.services.fiscal_year_service import generate_fy_rows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Natural sign by Xero account type (revenue/income = +1, costs/expenses = -1)
# ---------------------------------------------------------------------------
_NATURAL_SIGN_MAP = {
    "REVENUE": 1,
    "SALES": 1,
    "OTHERINCOME": 1,
    "DIRECTCOSTS": -1,
    "OVERHEADS": -1,
    "EXPENSE": -1,
    "OTHEREXPENSES": -1,
    "DEPRECIATN": -1,
    "SUPERANNUATIONEXPENSE": -1,
    "WAGESEXPENSE": -1,
}

XERO_API_BASE = "https://api.xero.com/api.xro/2.0"


# ---------------------------------------------------------------------------
# Keyword lists for OVERHEADS / EXPENSE sub-categorisation
# ---------------------------------------------------------------------------
_PAYROLL_KEYWORDS = [
    "salary", "salaries", "wage", "wages", "payroll", "pension",
    "ni", "national insurance", "employers",
]
_MARKETING_KEYWORDS = [
    "marketing", "advertising", "promotion", "campaign",
]
_TECH_KEYWORDS = [
    "software", "technology", "cloud", "hosting", "saas",
    "subscription", "it", "infrastructure",
]
_PROFESSIONAL_KEYWORDS = [
    "legal", "audit", "accountancy", "accountant", "professional",
    "solicitor", "consultant",
]


# ---------------------------------------------------------------------------
# Type-based mapping rules
# ---------------------------------------------------------------------------
_TYPE_RULES = {
    "REVENUE":    {"reporting_category": "Revenue",               "statement_type": "profit_and_loss", "pnl": True,  "bs": False},
    "SALES":      {"reporting_category": "Revenue",               "statement_type": "profit_and_loss", "pnl": True,  "bs": False},
    "DIRECTCOSTS":{"reporting_category": "Cost of Sales",         "statement_type": "profit_and_loss", "pnl": True,  "bs": False},
    "BANK":       {"reporting_category": "Cash & Bank",           "statement_type": "balance_sheet",   "pnl": False, "bs": True},
    "CURRENT":    {"reporting_category": "Current Assets",        "statement_type": "balance_sheet",   "pnl": False, "bs": True},
    "INVENTORY":  {"reporting_category": "Current Assets",        "statement_type": "balance_sheet",   "pnl": False, "bs": True},
    "FIXED":      {"reporting_category": "Fixed Assets",          "statement_type": "balance_sheet",   "pnl": False, "bs": True},
    "CURRLIAB":   {"reporting_category": "Current Liabilities",   "statement_type": "balance_sheet",   "pnl": False, "bs": True},
    "TERMLIAB":   {"reporting_category": "Long-term Liabilities", "statement_type": "balance_sheet",   "pnl": False, "bs": True},
    "EQUITY":     {"reporting_category": "Equity",                "statement_type": "balance_sheet",   "pnl": False, "bs": True},
}


def _classify_expense(account_name: str) -> str:
    """Sub-categorise OVERHEADS/EXPENSE accounts by keyword matching."""
    name_lower = account_name.lower()
    for kw in _PAYROLL_KEYWORDS:
        if kw in name_lower:
            return "Payroll & People Costs"
    for kw in _MARKETING_KEYWORDS:
        if kw in name_lower:
            return "Marketing & Sales"
    for kw in _TECH_KEYWORDS:
        if kw in name_lower:
            return "Technology & Infrastructure"
    for kw in _PROFESSIONAL_KEYWORDS:
        if kw in name_lower:
            return "Professional Fees"
    return "General & Administrative"


def _map_account(xero_type: str, account_name: str) -> dict:
    """
    Map a Xero account to reporting_category, statement_type, and flags.
    Returns dict with keys: reporting_category, statement_type,
    include_in_pnl, include_in_bs, is_mapped.
    """
    xero_type_upper = xero_type.upper()

    # Check OVERHEADS / EXPENSE first (needs keyword sub-categorisation)
    if xero_type_upper in ("OVERHEADS", "EXPENSE"):
        return {
            "reporting_category": _classify_expense(account_name),
            "statement_type": "profit_and_loss",
            "include_in_pnl": True,
            "include_in_bs": False,
            "is_mapped": True,
        }

    # Check type-based rules
    rule = _TYPE_RULES.get(xero_type_upper)
    if rule:
        return {
            "reporting_category": rule["reporting_category"],
            "statement_type": rule["statement_type"],
            "include_in_pnl": rule["pnl"],
            "include_in_bs": rule["bs"],
            "is_mapped": True,
        }

    # No rule matched — flag for Data Health review
    return {
        "reporting_category": None,
        "statement_type": None,
        "include_in_pnl": False,
        "include_in_bs": False,
        "is_mapped": False,
    }


# ---------------------------------------------------------------------------
# Main onboarding function
# ---------------------------------------------------------------------------
async def run_onboarding(db: AsyncSession, org_id: str) -> dict:
    """
    Run the full onboarding sequence after Xero OAuth connection.

    Steps:
      1. Fetch Xero Chart of Accounts
      2. Auto-map accounts into account_mappings
      3. Generate fiscal year rows
      4. Trigger initial 24-month P&L + BS sync
      5. Set onboarding_complete = true on the organisation

    Returns dict with: accounts_mapped, accounts_unmapped, fy_rows_created,
    sync_complete, onboarding_complete.
    """
    result = {
        "accounts_mapped": 0,
        "accounts_unmapped": 0,
        "fy_rows_created": False,
        "sync_complete": False,
        "onboarding_complete": False,
    }

    # -----------------------------------------------------------------------
    # Load Xero credentials
    # -----------------------------------------------------------------------
    creds = await db.execute(
        text(
            "SELECT access_token, xero_tenant_id "
            "FROM xero_connections "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"org_id": org_id},
    )
    row = creds.fetchone()
    if not row:
        logger.error(f"[ONBOARDING] No active Xero connection for org={org_id}")
        raise Exception("No active Xero connection found")

    access_token = row.access_token
    tenant_id = row.xero_tenant_id

    # -----------------------------------------------------------------------
    # STEP 1: Fetch Xero Chart of Accounts
    # -----------------------------------------------------------------------
    logger.info(f"[ONBOARDING] Step 1: Fetching Chart of Accounts for org={org_id}")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{XERO_API_BASE}/Accounts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    if resp.status_code != 200:
        logger.error(
            f"[ONBOARDING] Xero Chart of Accounts fetch failed: {resp.status_code} {resp.text}"
        )
        raise Exception(f"Xero API error: {resp.status_code}")

    accounts = resp.json().get("Accounts", [])
    logger.info(f"[ONBOARDING] Fetched {len(accounts)} accounts from Xero")

    # -----------------------------------------------------------------------
    # STEP 2 & 3: Map accounts and insert account_mappings rows
    # -----------------------------------------------------------------------
    logger.info(f"[ONBOARDING] Step 2: Mapping accounts for org={org_id}")
    mapped_count = 0
    unmapped_count = 0

    for acct in accounts:
        acct_status = acct.get("Status", "ACTIVE")
        if acct_status != "ACTIVE":
            continue

        xero_account_id = acct.get("AccountID", "")
        account_code = acct.get("Code", "")
        account_name = acct.get("Name", "")
        xero_type = acct.get("Type", "")

        try:
            mapping = _map_account(xero_type, account_name)

            await db.execute(
                text(
                    "INSERT INTO account_mappings "
                    "(id, organisation_id, xero_account_id, account_code, account_name, "
                    " xero_account_type, reporting_category, statement_type, natural_sign, "
                    " include_in_pnl, include_in_bs, is_mapped, created_at, updated_at) "
                    "VALUES "
                    "(:id, :org_id, :xero_account_id, :account_code, :account_name, "
                    " :xero_type, :category, :stmt_type, :sign, :pnl, :bs, :is_mapped, now(), now()) "
                    "ON CONFLICT (organisation_id, xero_account_id) DO UPDATE SET "
                    "  account_code = EXCLUDED.account_code, "
                    "  account_name = EXCLUDED.account_name, "
                    "  xero_account_type = EXCLUDED.xero_account_type, "
                    "  natural_sign = CASE "
                    "    WHEN account_mappings.is_mapped = false "
                    "    THEN EXCLUDED.natural_sign "
                    "    ELSE account_mappings.natural_sign END, "
                    "  reporting_category = CASE "
                    "    WHEN account_mappings.is_mapped = false "
                    "    THEN EXCLUDED.reporting_category "
                    "    ELSE account_mappings.reporting_category END, "
                    "  statement_type = CASE "
                    "    WHEN account_mappings.is_mapped = false "
                    "    THEN EXCLUDED.statement_type "
                    "    ELSE account_mappings.statement_type END, "
                    "  include_in_pnl = CASE "
                    "    WHEN account_mappings.is_mapped = false "
                    "    THEN EXCLUDED.include_in_pnl "
                    "    ELSE account_mappings.include_in_pnl END, "
                    "  include_in_bs = CASE "
                    "    WHEN account_mappings.is_mapped = false "
                    "    THEN EXCLUDED.include_in_bs "
                    "    ELSE account_mappings.include_in_bs END, "
                    "  is_mapped = CASE "
                    "    WHEN account_mappings.is_mapped = false "
                    "    THEN EXCLUDED.is_mapped "
                    "    ELSE account_mappings.is_mapped END, "
                    "  updated_at = now()"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "xero_account_id": xero_account_id,
                    "account_code": account_code or "",
                    "account_name": account_name or "",
                    "xero_type": xero_type,
                    "category": mapping["reporting_category"],
                    "stmt_type": mapping["statement_type"],
                    "sign": _NATURAL_SIGN_MAP.get(xero_type.upper(), 1),
                    "pnl": mapping["include_in_pnl"],
                    "bs": mapping["include_in_bs"],
                    "is_mapped": mapping["is_mapped"],
                },
            )

            if mapping["is_mapped"]:
                mapped_count += 1
            else:
                unmapped_count += 1

        except Exception as e:
            logger.warning(
                f"[ONBOARDING] Failed to map account {account_code} '{account_name}': {e}"
            )
            unmapped_count += 1
            continue

    await db.commit()
    result["accounts_mapped"] = mapped_count
    result["accounts_unmapped"] = unmapped_count
    logger.info(
        f"[ONBOARDING] Account mapping complete: mapped={mapped_count}, unmapped={unmapped_count}"
    )

    # -----------------------------------------------------------------------
    # STEP 4: Generate fiscal year rows
    # -----------------------------------------------------------------------
    logger.info(f"[ONBOARDING] Step 3: Generating fiscal year rows for org={org_id}")
    try:
        await generate_fy_rows(db, org_id, fy_start_month=4)
        result["fy_rows_created"] = True
        logger.info(f"[ONBOARDING] Fiscal year rows generated for org={org_id}")
    except Exception as e:
        logger.error(f"[ONBOARDING] Failed to generate FY rows for org={org_id}: {e}")

    # -----------------------------------------------------------------------
    # STEP 5: Initial 24-month sync (P&L + Balance Sheet)
    # -----------------------------------------------------------------------
    logger.info(f"[ONBOARDING] Step 4: Running initial 24-month sync for org={org_id}")
    try:
        # Import sync helpers from xero router (same pattern used by /sync endpoint)
        from app.routers.integrations.xero import _sync_pnl_monthly, _sync_bs_monthly

        today = date.today()
        sync_start = today - relativedelta(months=24)
        # Align to first of month
        sync_start = sync_start.replace(day=1)

        pnl_result = await _sync_pnl_monthly(
            db, org_id, access_token, tenant_id, sync_start, today
        )
        bs_result = await _sync_bs_monthly(
            db, org_id, access_token, tenant_id, sync_start, today
        )

        # Update last_sync_at
        now = datetime.now(timezone.utc)
        await db.execute(
            text(
                "UPDATE xero_connections SET last_sync_at = :now "
                "WHERE organisation_id = :org_id AND is_active = true"
            ),
            {"now": now, "org_id": org_id},
        )
        await db.commit()

        result["sync_complete"] = True
        logger.info(
            f"[ONBOARDING] Sync complete: P&L months={pnl_result['months_synced']}, "
            f"BS months={bs_result['months_synced']}"
        )
    except Exception as e:
        logger.error(f"[ONBOARDING] Initial sync failed for org={org_id}: {e}")

    # -----------------------------------------------------------------------
    # STEP 6: Set onboarding_complete on the organisation
    # -----------------------------------------------------------------------
    logger.info(f"[ONBOARDING] Step 5: Setting onboarding_complete for org={org_id}")
    try:
        await db.execute(
            text(
                "UPDATE organisations "
                "SET settings = jsonb_set(COALESCE(settings, '{}')::jsonb, "
                "    '{onboarding_complete}', 'true') "
                "WHERE id = :org_id"
            ),
            {"org_id": org_id},
        )
        await db.commit()
        result["onboarding_complete"] = True
        logger.info(f"[ONBOARDING] Onboarding complete for org={org_id}")
    except Exception as e:
        logger.error(f"[ONBOARDING] Failed to set onboarding_complete for org={org_id}: {e}")

    return result
