"""
FinSight AI - Xero Integration Router
======================================
OAuth 2.0 connection, data sync, Chart of Accounts auto-mapping.
Uses raw SQL pattern consistent with existing *-simple endpoints.

v2.5: Monthly P&L grain - fetches one report per calendar month,
      parses JSONB into financial_line_items for proper BvA reporting.
      Added backfill endpoint to repair existing stored JSONB.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone, timedelta, date
from calendar import monthrange
import httpx
import uuid
import logging
import os
import urllib.parse
import json

from app.core.encryption import encrypt_token, safe_decrypt

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.onboarding_service import run_onboarding
from app.services.auth_service import generate_slug
from sqlalchemy import select
from app.models.organisation import Organisation

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET", "")
XERO_REDIRECT_URI = os.getenv("XERO_REDIRECT_URI", "")
XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"
XERO_SCOPES = (
    "openid profile email "
    "accounting.transactions.read "
    "accounting.reports.read "
    "accounting.contacts.read "
    "accounting.settings.read "
    "accounting.budgets.read "
    "offline_access"
)

# After successful OAuth, redirect user here
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://finsightai-dashboard.netlify.app")


# ---------------------------------------------------------------------------
# Auto-mapping rules: Xero account type -> reporting category + sign
# ---------------------------------------------------------------------------
XERO_TYPE_MAPPING = {
    "REVENUE":        {"category": "Revenue",                  "sign": 1,  "pnl": True,  "bs": False},
    "DIRECTCOSTS":    {"category": "Cost of Sales",            "sign": -1, "pnl": True,  "bs": False},
    "EXPENSE":        {"category": "General & Administrative", "sign": -1, "pnl": True,  "bs": False},
    "OVERHEADS":      {"category": "General & Administrative", "sign": -1, "pnl": True,  "bs": False},
    "OTHERINCOME":    {"category": "Other Income",             "sign": 1,  "pnl": True,  "bs": False},
    "OTHEREXPENSE":   {"category": "Other Expense",            "sign": -1, "pnl": True,  "bs": False},
    "BANK":           {"category": "Cash & Bank",              "sign": 1,  "pnl": False, "bs": True},
    "CURRENT":        {"category": "Current Assets",           "sign": 1,  "pnl": False, "bs": True},
    "CURRLIAB":       {"category": "Current Liabilities",      "sign": -1, "pnl": False, "bs": True},
    "NONCURRENT":     {"category": "Non-current Assets",       "sign": 1,  "pnl": False, "bs": True},
    "TERMLIAB":       {"category": "Long-term Liabilities",    "sign": -1, "pnl": False, "bs": True},
    "EQUITY":         {"category": "Equity",                   "sign": 1,  "pnl": False, "bs": True},
    "FIXED":          {"category": "Fixed Assets",             "sign": 1,  "pnl": False, "bs": True},
    "PREPAYMENT":     {"category": "Current Assets",           "sign": 1,  "pnl": False, "bs": True},
    "SALES":          {"category": "Revenue",                  "sign": 1,  "pnl": True,  "bs": False},
    "DEPRECIATN":     {"category": "General & Administrative", "sign": -1, "pnl": True,  "bs": False},
    "INVENTORY":      {"category": "Current Assets",           "sign": 1,  "pnl": False, "bs": True},
    "PAYGLIABILITY":  {"category": "Current Liabilities",      "sign": -1, "pnl": False, "bs": True},
    "SUPERANNUATIONEXPENSE": {"category": "General & Administrative", "sign": -1, "pnl": True,  "bs": False},
    "SUPERANNUATIONLIABILITY": {"category": "Current Liabilities",    "sign": -1, "pnl": False, "bs": True},
    "WAGESEXPENSE":   {"category": "Payroll & People Costs",  "sign": -1, "pnl": True,  "bs": False},
}


# ---------------------------------------------------------------------------
# Helper: extract org_id from current_user (raw SQL pattern)
# ---------------------------------------------------------------------------
def _get_org_id(current_user) -> str:
    """Extract active_org_id from the authenticated user object."""
    org_id = getattr(current_user, "active_org_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation. Please connect a Xero account to continue."
        )
    return str(org_id)


# ---------------------------------------------------------------------------
# Helper: refresh Xero tokens if expired
# ---------------------------------------------------------------------------
async def _refresh_tokens_if_needed(db: AsyncSession, org_id: str) -> dict:
    """
    Check if Xero access token is expired. If so, refresh it.
    Returns dict with access_token and xero_tenant_id.
    """
    result = await db.execute(
        text(
            "SELECT id, access_token, refresh_token, token_expires_at, xero_tenant_id "
            "FROM xero_connections "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"org_id": org_id}
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active Xero connection found. Please connect Xero first."
        )

    now = datetime.now(timezone.utc)
    # Refresh if within 5 minutes of expiry
    if row.token_expires_at and row.token_expires_at > now + timedelta(minutes=5):
        return {
            "access_token": safe_decrypt(row.access_token),
            "xero_tenant_id": row.xero_tenant_id,
            "connection_id": str(row.id),
        }

    # Token expired or about to expire — refresh
    logger.info(f"[XERO] Refreshing tokens for org={org_id}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": safe_decrypt(row.refresh_token),
                "client_id": XERO_CLIENT_ID,
                "client_secret": XERO_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )

    if resp.status_code != 200:
        logger.error(f"[XERO] Token refresh failed: {resp.status_code} {resp.text}")
        # Mark connection as inactive
        await db.execute(
            text("UPDATE xero_connections SET is_active = false WHERE id = :id"),
            {"id": str(row.id)}
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Xero token refresh failed. Please reconnect Xero."
        )

    tokens = resp.json()
    new_expires = now + timedelta(seconds=tokens.get("expires_in", 1800))

    await db.execute(
        text(
            "UPDATE xero_connections "
            "SET access_token = :access_token, "
            "    refresh_token = :refresh_token, "
            "    token_expires_at = :expires_at "
            "WHERE id = :id"
        ),
        {
            "access_token": encrypt_token(tokens["access_token"]),
            "refresh_token": encrypt_token(
                tokens.get("refresh_token") or safe_decrypt(row.refresh_token)
            ),
            "expires_at": new_expires,
            "id": str(row.id),
        }
    )
    await db.commit()

    logger.info(f"[XERO] Tokens refreshed successfully for org={org_id}")
    return {
        "access_token": tokens["access_token"],
        "xero_tenant_id": row.xero_tenant_id,
        "connection_id": str(row.id),
    }


# ---------------------------------------------------------------------------
# Helper: sync Chart of Accounts into account_mappings
# ---------------------------------------------------------------------------
async def _sync_chart_of_accounts(
    db: AsyncSession,
    org_id: str,
    access_token: str,
    tenant_id: str,
) -> dict:
    """
    Pull Chart of Accounts from Xero and upsert into account_mappings.
    Applies auto-mapping rules for known Xero account types.
    Returns { total, mapped, unmapped }.
    """
    # Clear any aborted transaction from previous operations
    try:
        await db.rollback()
    except Exception:
        pass

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
        logger.error(f"[XERO] Failed to fetch Chart of Accounts: {resp.status_code}")
        return {"total": 0, "mapped": 0, "unmapped": 0}

    accounts = resp.json().get("Accounts", [])
    total = len(accounts)
    mapped = 0
    unmapped = 0

    for acct in accounts:
        xero_account_id = acct.get("AccountID", "")
        account_code = acct.get("Code", "")
        account_name = acct.get("Name", "")
        xero_type = acct.get("Type", "").upper()
        acct_status = acct.get("Status", "ACTIVE")

        # Skip archived accounts
        if acct_status == "ARCHIVED":
            continue

        # Look up auto-mapping rule
        rule = XERO_TYPE_MAPPING.get(xero_type)
        if rule:
            category = rule["category"]
            sign = rule["sign"]
            pnl = rule["pnl"]
            bs = rule["bs"]
            is_mapped = True
            mapped += 1
        else:
            category = "UNMAPPED"
            sign = 1
            pnl = False
            bs = False
            is_mapped = False
            unmapped += 1

        # Upsert into account_mappings
        await db.execute(
            text(
                "INSERT INTO account_mappings "
                "(id, organisation_id, xero_account_id, account_code, account_name, "
                " xero_account_type, reporting_category, natural_sign, "
                " include_in_pnl, include_in_bs, is_mapped, created_at, updated_at) "
                "VALUES "
                "(:id, :org_id, :xero_account_id, :account_code, :account_name, "
                " :xero_type, :category, :sign, :pnl, :bs, :is_mapped, now(), now()) "
                "ON CONFLICT (organisation_id, xero_account_id) DO UPDATE SET "
                "  account_code = EXCLUDED.account_code, "
                "  account_name = EXCLUDED.account_name, "
                "  xero_account_type = EXCLUDED.xero_account_type, "
                "  reporting_category = CASE "
                "    WHEN account_mappings.is_mapped = true THEN account_mappings.reporting_category "
                "    ELSE EXCLUDED.reporting_category END, "
                "  natural_sign = CASE "
                "    WHEN account_mappings.is_mapped = true THEN account_mappings.natural_sign "
                "    ELSE EXCLUDED.natural_sign END, "
                "  include_in_pnl = CASE "
                "    WHEN account_mappings.is_mapped = true THEN account_mappings.include_in_pnl "
                "    ELSE EXCLUDED.include_in_pnl END, "
                "  include_in_bs = CASE "
                "    WHEN account_mappings.is_mapped = true THEN account_mappings.include_in_bs "
                "    ELSE EXCLUDED.include_in_bs END, "
                "  is_mapped = CASE "
                "    WHEN account_mappings.is_mapped = true THEN true "
                "    ELSE EXCLUDED.is_mapped END, "
                "  updated_at = now()"
            ),
            {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "xero_account_id": xero_account_id,
                "account_code": account_code or "",
                "account_name": account_name or "",
                "xero_type": xero_type,
                "category": category,
                "sign": sign,
                "pnl": pnl,
                "bs": bs,
                "is_mapped": is_mapped,
            }
        )

    await db.commit()
    logger.info(f"[XERO] Chart of Accounts synced: total={total}, mapped={mapped}, unmapped={unmapped}")
    return {"total": total, "mapped": mapped, "unmapped": unmapped}


# ---------------------------------------------------------------------------
# Helper: generate (period_start, period_end) tuples for each calendar month
# ---------------------------------------------------------------------------
def _months_in_range(from_date: date, to_date: date):
    """Yield (first_of_month, last_of_month) for every month from_date..to_date."""
    current = from_date.replace(day=1)
    while current <= to_date:
        last_day = monthrange(current.year, current.month)[1]
        month_end = current.replace(day=last_day)
        yield current, min(month_end, to_date)
        # Advance to first of next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)


# ---------------------------------------------------------------------------
# Helper: parse Xero P&L report JSON into flat account rows
# ---------------------------------------------------------------------------
def _parse_pnl_rows(report_json: dict) -> list[dict]:
    """
    Walk the nested Xero P&L Rows structure.
    Returns list of dicts: {xero_account_id, account_name, net_amount}
    Skips Header and SummaryRow rows.
    """
    rows = []
    reports = report_json.get("Reports", [])
    if not reports:
        return rows

    def _walk(row_list):
        for row in row_list:
            row_type = row.get("RowType", "")
            if row_type in ("Header", "SummaryRow"):
                continue
            if row_type == "Section":
                _walk(row.get("Rows", []))
                continue
            if row_type == "Row":
                cells = row.get("Cells", [])
                if len(cells) < 2:
                    continue
                account_cell = cells[0]
                amount_cell = cells[-1]
                account_name = account_cell.get("Value", "")
                xero_account_id = None
                for attr in account_cell.get("Attributes", []):
                    if attr.get("Id") == "account":
                        xero_account_id = attr.get("Value")
                        break
                try:
                    net_amount = float(amount_cell.get("Value") or 0)
                except (ValueError, TypeError):
                    net_amount = 0.0
                rows.append({
                    "xero_account_id": xero_account_id,
                    "account_name": account_name,
                    "net_amount": net_amount,
                })

    _walk(reports[0].get("Rows", []))
    return rows


# ---------------------------------------------------------------------------
# Helper: upsert parsed line items into financial_line_items
# ---------------------------------------------------------------------------
async def _upsert_line_items(
    db: AsyncSession,
    org_id: str,
    period_start: date,
    period_end: date,
    line_items: list[dict],
    fetched_at: datetime,
    report_type: str = "ProfitAndLoss",
) -> int:
    """Insert/update rows in financial_line_items. Returns count upserted."""
    count = 0
    for item in line_items:
        xero_account_id = item.get("xero_account_id")
        if not xero_account_id:
            continue  # Skip rows with no account ID (subtotals etc.)
        await db.execute(
            text(
                "INSERT INTO financial_line_items "
                "(id, organisation_id, xero_account_id, account_name, report_type, "
                " period_start, period_end, net_amount, fetched_at) "
                "VALUES (:id, :org_id, :xero_account_id, :account_name, :report_type, "
                " :period_start, :period_end, :net_amount, :fetched_at) "
                "ON CONFLICT (organisation_id, xero_account_id, report_type, period_start, period_end) "
                "DO UPDATE SET "
                "  net_amount = EXCLUDED.net_amount, "
                "  fetched_at = EXCLUDED.fetched_at"
            ),
            {
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "xero_account_id": xero_account_id,
                "account_name": item.get("account_name", ""),
                "report_type": report_type,
                "period_start": period_start,
                "period_end": period_end,
                "net_amount": item.get("net_amount", 0.0),
                "fetched_at": fetched_at,
            }
        )
        count += 1
    await db.commit()
    return count


# ---------------------------------------------------------------------------
# Helper: fetch one P&L per calendar month and populate financial_line_items
# ---------------------------------------------------------------------------
async def _sync_pnl_monthly(
    db: AsyncSession,
    org_id: str,
    access_token: str,
    tenant_id: str,
    fy_start: date,
    today: date,
) -> dict:
    """
    Fetches Xero P&L month by month from fy_start to today.
    Stores raw JSONB in financial_data and parsed rows in financial_line_items.
    Returns { months_synced, line_items_upserted, errors }.
    """
    now = datetime.now(timezone.utc)
    months_synced = 0
    total_upserted = 0
    errors = []

    for period_start, period_end in _months_in_range(fy_start, today):
        try:
            logger.info(
                f"[XERO] Fetching P&L month {period_start} -> {period_end} for org={org_id}"
            )
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{XERO_API_BASE}/Reports/ProfitAndLoss",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Xero-Tenant-Id": tenant_id,
                        "Accept": "application/json",
                    },
                    params={
                        "fromDate": period_start.isoformat(),
                        "toDate": period_end.isoformat(),
                    },
                    timeout=30.0,
                )

            if resp.status_code != 200:
                errors.append(f"{period_start}: HTTP {resp.status_code}")
                logger.error(
                    f"[XERO] P&L fetch failed for {period_start}: {resp.status_code}"
                )
                continue

            pl_data = resp.json()

            # Store raw JSONB
            await db.execute(
                text(
                    "INSERT INTO financial_data "
                    "(id, organisation_id, report_type, period_start, period_end, data, fetched_at) "
                    "VALUES (:id, :org_id, 'ProfitAndLoss', :start, :end, :data, :fetched) "
                    "ON CONFLICT (organisation_id, report_type, period_start, period_end) "
                    "DO UPDATE SET data = EXCLUDED.data, fetched_at = EXCLUDED.fetched_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "start": period_start,
                    "end": period_end,
                    "data": json.dumps(pl_data),
                    "fetched": now,
                }
            )
            await db.commit()

            # Parse and upsert line items
            line_items = _parse_pnl_rows(pl_data)
            upserted = await _upsert_line_items(
                db, org_id, period_start, period_end, line_items, now
            )
            total_upserted += upserted
            months_synced += 1
            logger.info(
                f"[XERO] Month {period_start}: {upserted} line items upserted"
            )

        except Exception as e:
            logger.error(
                f"[XERO] Monthly P&L sync error for {period_start}: {type(e).__name__}: {e}"
            )
            errors.append(f"{period_start}: {type(e).__name__}: {e}")

    return {
        "months_synced": months_synced,
        "line_items_upserted": total_upserted,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Helper: fetch BS per calendar month-end and populate financial_line_items
# ---------------------------------------------------------------------------
async def _sync_bs_monthly(
    db: AsyncSession,
    org_id: str,
    access_token: str,
    tenant_id: str,
    fy_start: date,
    today: date,
) -> dict:
    """
    Fetches Xero Balance Sheet at each month-end from fy_start to today.
    Stores raw JSONB in financial_data and parsed rows in financial_line_items.
    Returns { months_synced, line_items_upserted, errors }.
    """
    now = datetime.now(timezone.utc)
    months_synced = 0
    total_upserted = 0
    errors = []

    for period_start, period_end in _months_in_range(fy_start, today):
        try:
            logger.info(
                f"[XERO] Fetching BS snapshot {period_end} for org={org_id}"
            )
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{XERO_API_BASE}/Reports/BalanceSheet",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Xero-Tenant-Id": tenant_id,
                        "Accept": "application/json",
                    },
                    params={
                        "date": period_end.isoformat(),
                    },
                    timeout=30.0,
                )

            if resp.status_code != 200:
                errors.append(f"BS {period_end}: HTTP {resp.status_code}")
                logger.error(
                    f"[XERO] BS fetch failed for {period_end}: {resp.status_code}"
                )
                continue

            bs_data = resp.json()

            # Store raw JSONB
            await db.execute(
                text(
                    "INSERT INTO financial_data "
                    "(id, organisation_id, report_type, period_start, period_end, data, fetched_at) "
                    "VALUES (:id, :org_id, 'BalanceSheet', :start, :end, :data, :fetched) "
                    "ON CONFLICT (organisation_id, report_type, period_start, period_end) "
                    "DO UPDATE SET data = EXCLUDED.data, fetched_at = EXCLUDED.fetched_at"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "start": period_start,
                    "end": period_end,
                    "data": json.dumps(bs_data),
                    "fetched": now,
                }
            )
            await db.commit()

            # Parse and upsert line items
            line_items = _parse_pnl_rows(bs_data)
            upserted = await _upsert_line_items(
                db, org_id, period_start, period_end, line_items, now,
                report_type="BalanceSheet",
            )
            total_upserted += upserted
            months_synced += 1
            logger.info(
                f"[XERO] BS {period_end}: {upserted} line items upserted"
            )

        except Exception as e:
            logger.error(
                f"[XERO] Monthly BS sync error for {period_end}: {type(e).__name__}: {e}"
            )
            errors.append(f"BS {period_end}: {type(e).__name__}: {e}")

    return {
        "months_synced": months_synced,
        "line_items_upserted": total_upserted,
        "errors": errors,
    }


# ===================================================================
# ENDPOINTS
# ===================================================================


@router.get("/connect")
async def xero_connect(
    request: Request,
    token: str = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate Xero OAuth 2.0 Authorization Code flow.
    Accepts JWT via Authorization header OR ?token= query parameter (dev mode).
    Redirects user to Xero login page.

    State parameter carries user_id (not org_id) so the callback can
    create a new organisation for multi-org connect.
    """
    from app.core.security import decode_token as _decode

    # Try header first, fall back to query param
    auth_header = request.headers.get("authorization", "")
    jwt_token = None

    if auth_header.startswith("Bearer "):
        jwt_token = auth_header.split(" ", 1)[1]
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Provide JWT via Authorization header or ?token= parameter"
        )

    payload = _decode(jwt_token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token — no user identifier"
        )

    if not XERO_CLIENT_ID or not XERO_REDIRECT_URI:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Xero OAuth not configured. Check XERO_CLIENT_ID and XERO_REDIRECT_URI."
        )

    # State parameter encodes user_id for the callback (multi-org aware)
    state = f"{user_id}:{uuid.uuid4().hex[:16]}"

    params = {
        "response_type": "code",
        "client_id": XERO_CLIENT_ID,
        "redirect_uri": XERO_REDIRECT_URI,
        "scope": XERO_SCOPES,
        "state": state,
    }

    auth_url = f"{XERO_AUTH_URL}?{urllib.parse.urlencode(params)}"
    logger.info(f"[XERO] Redirecting user={user_id} to Xero OAuth")
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def xero_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Xero OAuth callback. Exchanges code for tokens, stores connection.
    NOTE: This endpoint does NOT require JWT auth — Xero redirects here directly.
    The user_id is recovered from the state parameter.

    Multi-org aware: creates a new organisation for each Xero tenant connected.
    Dedup guard prevents the same tenant being connected twice by the same user.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error")

    if error:
        logger.error(f"[XERO] OAuth error: {error}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?xero_error={error}"
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorisation code")

    # Extract user_id from state (multi-org: state carries user_id, not org_id)
    user_id = state.split(":")[0] if ":" in state else ""
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": XERO_REDIRECT_URI,
                "client_id": XERO_CLIENT_ID,
                "client_secret": XERO_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )

    if resp.status_code != 200:
        logger.error(f"[XERO] Token exchange failed: {resp.status_code} {resp.text}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?xero_error=token_exchange_failed"
        )

    tokens = resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")
    expires_in = tokens.get("expires_in", 1800)
    token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Fetch tenant connections
    async with httpx.AsyncClient() as client:
        conn_resp = await client.get(
            XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )

    if conn_resp.status_code != 200:
        logger.error(f"[XERO] Failed to fetch connections: {conn_resp.status_code}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?xero_error=connections_failed"
        )

    connections = conn_resp.json()
    if not connections:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?xero_error=no_tenants"
        )

    # Use first tenant
    tenant = connections[0]
    tenant_id = tenant.get("tenantId", "")
    tenant_name = tenant.get("tenantName", "")

    # -----------------------------------------------------------------------
    # DEDUP CHECK: does this user already have an org connected to this tenant?
    # -----------------------------------------------------------------------
    dedup = await db.execute(
        text(
            "SELECT xc.organisation_id FROM xero_connections xc "
            "JOIN organisation_members om ON om.organisation_id = xc.organisation_id "
            "WHERE om.user_id = :user_id "
            "  AND xc.xero_tenant_id = :tenant_id "
            "  AND xc.is_active = true "
            "LIMIT 1"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )
    if dedup.fetchone():
        logger.warning(
            f"[XERO] Dedup: user={user_id} already has tenant={tenant_id} connected"
        )
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?xero_error=already_connected"
        )

    # -----------------------------------------------------------------------
    # Check if user already has any orgs (determines first vs additional connect)
    # -----------------------------------------------------------------------
    existing_orgs = await db.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM organisation_members WHERE user_id = :user_id"
        ),
        {"user_id": user_id},
    )
    is_first_connect = existing_orgs.scalar_one() == 0

    # -----------------------------------------------------------------------
    # Create new organisation for this Xero tenant
    # -----------------------------------------------------------------------
    org_name = tenant_name or "Unnamed Organisation"
    base_slug = generate_slug(org_name)
    slug = base_slug
    counter = 1
    while True:
        slug_check = await db.execute(
            select(Organisation).where(Organisation.slug == slug)
        )
        if not slug_check.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    new_org_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO organisations (id, name, slug, subscription_tier, subscription_status, settings, created_at, updated_at) "
            "VALUES (:id, :name, :slug, 'essentials', 'trial', '{}', now(), now())"
        ),
        {"id": new_org_id, "name": org_name, "slug": slug},
    )

    # Insert organisation_members row (user owns this new org)
    await db.execute(
        text(
            "INSERT INTO organisation_members (id, organisation_id, user_id, role, joined_at) "
            "VALUES (:id, :org_id, :user_id, 'owner', now()) "
            "ON CONFLICT (organisation_id, user_id) DO NOTHING"
        ),
        {"id": str(uuid.uuid4()), "org_id": new_org_id, "user_id": user_id},
    )

    # Set active_org_id (and legacy organisation_id on first connect only)
    if is_first_connect:
        await db.execute(
            text(
                "UPDATE users SET active_org_id = :org_id, organisation_id = :org_id "
                "WHERE id = :user_id"
            ),
            {"org_id": new_org_id, "user_id": user_id},
        )
    else:
        await db.execute(
            text("UPDATE users SET active_org_id = :org_id WHERE id = :user_id"),
            {"org_id": new_org_id, "user_id": user_id},
        )

    org_id = new_org_id
    logger.info(
        f"[XERO] Created org={org_id} (name={org_name}) for user={user_id} "
        f"(first_connect={is_first_connect})"
    )

    # -----------------------------------------------------------------------
    # Upsert xero_connections (one connection per org — each new org gets its own row)
    # -----------------------------------------------------------------------
    connection_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO xero_connections "
            "(id, organisation_id, xero_tenant_id, xero_tenant_name, "
            " access_token, refresh_token, token_expires_at, scopes, "
            " connected_at, is_active) "
            "VALUES "
            "(:id, :org_id, :tenant_id, :tenant_name, "
            " :access_token, :refresh_token, :expires_at, :scopes, "
            " now(), true) "
            "ON CONFLICT (organisation_id) DO UPDATE SET "
            "  xero_tenant_id = EXCLUDED.xero_tenant_id, "
            "  xero_tenant_name = EXCLUDED.xero_tenant_name, "
            "  access_token = EXCLUDED.access_token, "
            "  refresh_token = EXCLUDED.refresh_token, "
            "  token_expires_at = EXCLUDED.token_expires_at, "
            "  scopes = EXCLUDED.scopes, "
            "  connected_at = now(), "
            "  is_active = true"
        ),
        {
            "id": connection_id,
            "org_id": org_id,
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "access_token": encrypt_token(access_token),
            "refresh_token": encrypt_token(refresh_token) if refresh_token else "",
            "expires_at": token_expires_at,
            "scopes": XERO_SCOPES,
        }
    )
    await db.commit()

    logger.info(f"[XERO] Connected org={org_id} to tenant={tenant_name} ({tenant_id})")

    # Run onboarding: map accounts, generate FY rows, initial sync
    try:
        await run_onboarding(db, org_id)
    except Exception as e:
        logger.error(f"[XERO] Onboarding failed for org={org_id}: {e}")

    return RedirectResponse(
        url=f"{FRONTEND_URL}/?xero_connected=true"
    )


@router.get("/status")
async def xero_status(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check Xero connection status for this organisation.
    """
    org_id = _get_org_id(current_user)

    result = await db.execute(
        text(
            "SELECT xero_tenant_name, last_sync_at, is_active, connected_at "
            "FROM xero_connections "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"org_id": org_id}
    )
    row = result.fetchone()

    if not row:
        return {
            "connected": False,
            "tenant_name": None,
            "last_sync_at": None,
            "connected_at": None,
        }

    return {
        "connected": True,
        "tenant_name": row.xero_tenant_name,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
    }


@router.post("/sync")
async def xero_sync(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync financial data from Xero.
    - Fetches P&L month-by-month for the current financial year
    - Stores raw JSONB in financial_data
    - Parses and upserts account-level rows into financial_line_items
    - Syncs Balance Sheet (point-in-time, today)
    - Syncs Chart of Accounts into account_mappings
    """
    org_id = _get_org_id(current_user)

    creds = await _refresh_tokens_if_needed(db, org_id)
    access_token = creds["access_token"]
    tenant_id = creds["xero_tenant_id"]

    now = datetime.now(timezone.utc)
    today = date.today()
    fy_start = date(today.year, 1, 1)

    reports_synced = []
    errors = []

    # --- Monthly P&L sync -> financial_line_items ---
    pnl_result = await _sync_pnl_monthly(
        db, org_id, access_token, tenant_id, fy_start, today
    )
    if pnl_result["months_synced"] > 0:
        reports_synced.append("ProfitAndLoss")
    errors.extend(pnl_result.get("errors", []))

    # --- Monthly Balance Sheet sync -> financial_line_items ---
    bs_result = await _sync_bs_monthly(
        db, org_id, access_token, tenant_id, fy_start, today
    )
    if bs_result["months_synced"] > 0:
        reports_synced.append("BalanceSheet")
    errors.extend(bs_result.get("errors", []))

    # --- Chart of Accounts ---
    coa_stats = await _sync_chart_of_accounts(db, org_id, access_token, tenant_id)

    # Update last_sync_at
    await db.execute(
        text(
            "UPDATE xero_connections SET last_sync_at = :now "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"now": now, "org_id": org_id}
    )
    await db.commit()

    result = {
        "success": True,
        "reports_synced": reports_synced,
        "months_synced": pnl_result["months_synced"] + bs_result["months_synced"],
        "line_items_upserted": pnl_result["line_items_upserted"] + bs_result["line_items_upserted"],
        "synced_at": now.isoformat(),
        "accounts_total": coa_stats["total"],
        "accounts_mapped": coa_stats["mapped"],
        "accounts_unmapped": coa_stats["unmapped"],
        "mapping_complete": coa_stats["unmapped"] == 0,
    }
    if errors:
        result["errors"] = errors
    return result


class SyncRangeRequest(BaseModel):
    from_date: date
    to_date: date


@router.post("/sync-range")
async def xero_sync_range(
    body: SyncRangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Backfill historical P&L data from Xero for an arbitrary date range.
    Calls _sync_pnl_monthly() with the provided from_date and to_date.
    """
    # Validate from_date < to_date
    if body.from_date >= body.to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_date must be before to_date",
        )

    # Validate range <= 24 months
    month_diff = (
        (body.to_date.year - body.from_date.year) * 12
        + body.to_date.month - body.from_date.month
    )
    if month_diff > 24:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date range must not exceed 24 months",
        )

    org_id = _get_org_id(current_user)

    creds = await _refresh_tokens_if_needed(db, org_id)
    access_token = creds["access_token"]
    tenant_id = creds["xero_tenant_id"]

    now = datetime.now(timezone.utc)

    pnl_result = await _sync_pnl_monthly(
        db, org_id, access_token, tenant_id, body.from_date, body.to_date
    )

    bs_result = await _sync_bs_monthly(
        db, org_id, access_token, tenant_id, body.from_date, body.to_date
    )

    # Update last_sync_at
    await db.execute(
        text(
            "UPDATE xero_connections SET last_sync_at = :now "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"now": now, "org_id": org_id},
    )
    await db.commit()

    reports_synced = []
    if pnl_result["months_synced"] > 0:
        reports_synced.append("ProfitAndLoss")
    if bs_result["months_synced"] > 0:
        reports_synced.append("BalanceSheet")

    all_errors = pnl_result.get("errors", []) + bs_result.get("errors", [])

    result = {
        "success": True,
        "reports_synced": reports_synced,
        "months_synced": pnl_result["months_synced"] + bs_result["months_synced"],
        "line_items_upserted": pnl_result["line_items_upserted"] + bs_result["line_items_upserted"],
        "synced_at": now.isoformat(),
    }
    if all_errors:
        result["errors"] = all_errors
    return result


@router.post("/backfill-line-items")
async def xero_backfill_line_items(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    One-time repair: re-parse existing financial_data JSONB blobs into financial_line_items.
    Safe to run multiple times — uses ON CONFLICT upsert.
    Run this once after deploying, then run /sync to fetch proper monthly grain.
    """
    org_id = _get_org_id(current_user)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text(
            "SELECT period_start, period_end, data "
            "FROM financial_data "
            "WHERE organisation_id = :org_id "
            "  AND report_type = 'ProfitAndLoss' "
            "ORDER BY period_start"
        ),
        {"org_id": org_id}
    )
    rows = result.fetchall()

    total_upserted = 0
    processed = 0

    for row in rows:
        try:
            raw = row.data
            if isinstance(raw, str):
                pl_data = json.loads(raw)
            else:
                pl_data = raw  # already dict (Neon returns parsed JSONB)

            line_items = _parse_pnl_rows(pl_data)
            upserted = await _upsert_line_items(
                db, org_id, row.period_start, row.period_end, line_items, now
            )
            total_upserted += upserted
            processed += 1
        except Exception as e:
            logger.error(
                f"[XERO] Backfill error for {row.period_start}: {type(e).__name__}: {e}"
            )

    return {
        "success": True,
        "message": "Backfill complete. Run /sync to fetch proper monthly grain.",
        "rows_processed": processed,
        "line_items_upserted": total_upserted,
    }


@router.delete("/disconnect")
async def xero_disconnect(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect Xero for this organisation.
    Marks connection as inactive and attempts to revoke tokens.
    """
    org_id = _get_org_id(current_user)

    # Always clear onboarding_complete so /auth/me reports xero_connected = false,
    # even if xero_connections.is_active was already set to false by a prior attempt.
    await db.execute(
        text(
            "UPDATE organisations "
            "SET settings = jsonb_set(COALESCE(settings, '{}')::jsonb, '{onboarding_complete}', '\"false\"') "
            "WHERE id = :org_id"
        ),
        {"org_id": org_id},
    )

    # Get current connection
    result = await db.execute(
        text(
            "SELECT id, access_token FROM xero_connections "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"org_id": org_id}
    )
    row = result.fetchone()

    if not row:
        await db.commit()
        logger.info(f"[XERO] Disconnected org={org_id} (no active connection, cleared onboarding flag)")
        return {"success": True, "message": "Xero disconnected successfully"}

    # Attempt to revoke token (best effort)
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                XERO_CONNECTIONS_URL,
                headers={"Authorization": f"Bearer {safe_decrypt(row.access_token)}"},
                timeout=10.0,
            )
    except Exception as e:
        logger.warning(f"[XERO] Token revocation failed (non-critical): {e}")

    # Mark as inactive
    await db.execute(
        text(
            "UPDATE xero_connections SET is_active = false "
            "WHERE id = :id"
        ),
        {"id": str(row.id)}
    )

    await db.commit()

    logger.info(f"[XERO] Disconnected org={org_id}")
    return {"success": True, "message": "Xero disconnected successfully"}


# ---------------------------------------------------------------------------
# Sync Xero Budgets → budget_monthly
# ---------------------------------------------------------------------------
@router.post("/sync-budgets")
async def xero_sync_budgets(
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch budgets from Xero and upsert into budget_monthly.
    Requires accounting.budgets.read scope (user must re-auth if scope was added after initial connect).
    """
    org_id = _get_org_id(current_user)
    logger.info(f"[BUDGET-SYNC] Starting for org={org_id}")

    creds = await _refresh_tokens_if_needed(db, org_id)
    access_token = creds["access_token"]
    tenant_id = creds["xero_tenant_id"]

    # Fetch budgets from Xero
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{XERO_API_BASE}/Budgets",
            headers={
                "Authorization": f"Bearer {access_token}",
                "xero-tenant-id": tenant_id,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    if resp.status_code != 200:
        logger.error(f"[BUDGET-SYNC] Xero API error: {resp.status_code} {resp.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Xero Budgets API returned {resp.status_code}",
        )

    data = resp.json()
    budgets = data.get("Budgets", [])
    logger.info(f"[BUDGET-SYNC] Found {len(budgets)} budgets")

    if not budgets:
        return {
            "budgets_found": 0,
            "lines_synced": 0,
            "periods_covered": "",
            "source": "xero",
        }

    # Fetch full detail for each budget (list endpoint omits BudgetLines)
    budget_details = []
    async with httpx.AsyncClient() as client:
        for budget_summary in budgets:
            budget_id = budget_summary.get("BudgetID")
            if not budget_id:
                continue
            logger.info(f"[BUDGET-SYNC] Fetching detail for BudgetID={budget_id}")
            detail_resp = await client.get(
                f"{XERO_API_BASE}/Budgets/{budget_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "xero-tenant-id": tenant_id,
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
            if detail_resp.status_code != 200:
                logger.error(
                    f"[BUDGET-SYNC] Detail fetch failed for {budget_id}: "
                    f"{detail_resp.status_code} {detail_resp.text}"
                )
                continue
            detail_data = detail_resp.json()
            detail_budgets = detail_data.get("Budgets", [])
            if detail_budgets:
                detail = detail_budgets[0]
                budget_details.append(detail)

    # Build lookup of account_code -> (account_name, reporting_category)
    acct_result = await db.execute(
        text(
            "SELECT account_code, account_name, reporting_category "
            "FROM account_mappings "
            "WHERE organisation_id = :org_id"
        ),
        {"org_id": org_id},
    )
    acct_map = {
        row.account_code: (row.account_name, row.reporting_category)
        for row in acct_result.fetchall()
    }
    lines_synced = 0
    all_periods: set[str] = set()

    for budget in budget_details:
        budget_lines = budget.get("BudgetLines", [])
        for line in budget_lines:
            account_code = line.get("AccountCode", "")
            if not account_code:
                continue

            account_name, reporting_category = acct_map.get(
                account_code, (f"Unknown ({account_code})", "UNMAPPED")
            )

            for bal in line.get("BudgetBalances", []):
                amount = bal.get("Amount")
                if not amount:
                    continue

                period_raw = bal.get("Period", "")
                if len(period_raw) < 7:
                    continue
                period = period_raw[:7]  # "2025-04-01T00:00:00" → "2025-04"
                all_periods.add(period)

                await db.execute(
                    text(
                        "INSERT INTO budget_monthly "
                        "  (id, organisation_id, account_code, account_name, "
                        "   reporting_category, period, budget_amount, source, "
                        "   created_at, updated_at) "
                        "VALUES "
                        "  (:id, :org_id, :account_code, :account_name, "
                        "   :reporting_category, :period, :amount, 'xero_sync', "
                        "   now(), now()) "
                        "ON CONFLICT (organisation_id, account_code, period) "
                        "DO UPDATE SET "
                        "  budget_amount = EXCLUDED.budget_amount, "
                        "  account_name = EXCLUDED.account_name, "
                        "  reporting_category = EXCLUDED.reporting_category, "
                        "  source = EXCLUDED.source, "
                        "  updated_at = now()"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": org_id,
                        "account_code": account_code,
                        "account_name": account_name,
                        "reporting_category": reporting_category,
                        "period": period,
                        "amount": float(amount),
                    },
                )
                lines_synced += 1

    await db.commit()

    sorted_periods = sorted(all_periods)
    periods_str = f"{sorted_periods[0]} to {sorted_periods[-1]}" if sorted_periods else ""
    logger.info(
        f"[BUDGET-SYNC] Synced {lines_synced} lines across "
        f"{len(sorted_periods)} periods for org={org_id}"
    )

    return {
        "budgets_found": len(budgets),
        "lines_synced": lines_synced,
        "periods_covered": periods_str,
        "source": "xero",
    }
