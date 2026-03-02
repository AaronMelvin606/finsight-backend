"""
FinSight AI - Xero Integration Router
======================================
OAuth 2.0 connection, data sync, Chart of Accounts auto-mapping.
Uses raw SQL pattern consistent with existing *-simple endpoints.

v2.3: Includes account_mappings auto-population on sync.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
import httpx
import uuid
import logging
import os
import urllib.parse
import json

from app.core.database import get_db
from app.core.security import get_current_user

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
    "offline_access"
)

# After successful OAuth, redirect user here
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.finsightai.tech")


# ---------------------------------------------------------------------------
# Auto-mapping rules: Xero account type -> reporting category + sign
# ---------------------------------------------------------------------------
XERO_TYPE_MAPPING = {
    "REVENUE":        {"category": "REVENUE",              "sign": 1,  "pnl": True,  "bs": False},
    "DIRECTCOSTS":    {"category": "COGS",                 "sign": -1, "pnl": True,  "bs": False},
    "EXPENSE":        {"category": "OPEX",                 "sign": -1, "pnl": True,  "bs": False},
    "OVERHEADS":      {"category": "OPEX",                 "sign": -1, "pnl": True,  "bs": False},
    "OTHERINCOME":    {"category": "OTHER_INCOME",         "sign": 1,  "pnl": True,  "bs": False},
    "OTHEREXPENSE":   {"category": "OTHER_EXPENSE",        "sign": -1, "pnl": True,  "bs": False},
    "BANK":           {"category": "BANK",                 "sign": 1,  "pnl": False, "bs": True},
    "CURRENT":        {"category": "CURRENT_ASSET",        "sign": 1,  "pnl": False, "bs": True},
    "CURRLIAB":       {"category": "CURRENT_LIABILITY",    "sign": -1, "pnl": False, "bs": True},
    "NONCURRENT":     {"category": "NON_CURRENT_ASSET",    "sign": 1,  "pnl": False, "bs": True},
    "TERMLIAB":       {"category": "NON_CURRENT_LIABILITY","sign": -1, "pnl": False, "bs": True},
    "EQUITY":         {"category": "EQUITY",               "sign": 1,  "pnl": False, "bs": True},
    "FIXED":          {"category": "NON_CURRENT_ASSET",    "sign": 1,  "pnl": False, "bs": True},
    "PREPAYMENT":     {"category": "CURRENT_ASSET",        "sign": 1,  "pnl": False, "bs": True},
    "SALES":          {"category": "REVENUE",              "sign": 1,  "pnl": True,  "bs": False},
    "DEPRECIATN":     {"category": "OPEX",                 "sign": -1, "pnl": True,  "bs": False},
    "PAYGLIABILITY":  {"category": "CURRENT_LIABILITY",    "sign": -1, "pnl": False, "bs": True},
    "SUPERANNUATIONEXPENSE": {"category": "OPEX",          "sign": -1, "pnl": True,  "bs": False},
    "SUPERANNUATIONLIABILITY": {"category": "CURRENT_LIABILITY", "sign": -1, "pnl": False, "bs": True},
    "WAGESEXPENSE":   {"category": "OPEX",                 "sign": -1, "pnl": True,  "bs": False},
}


# ---------------------------------------------------------------------------
# Helper: extract org_id from current_user (raw SQL pattern)
# ---------------------------------------------------------------------------
def _get_org_id(current_user) -> str:
    """Extract organisation_id from the authenticated user object."""
    org_id = getattr(current_user, "organisation_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with an organisation"
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
            "access_token": row.access_token,
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
                "refresh_token": row.refresh_token,
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
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", row.refresh_token),
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


# ===================================================================
# ENDPOINTS
# ===================================================================


@router.get("/connect")
async def xero_connect(
    current_user=Depends(get_current_user),
):
    """
    Initiate Xero OAuth 2.0 Authorization Code flow.
    Redirects user to Xero login page.
    """
    org_id = _get_org_id(current_user)

    if not XERO_CLIENT_ID or not XERO_REDIRECT_URI:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Xero OAuth not configured. Check XERO_CLIENT_ID and XERO_REDIRECT_URI."
        )

    # State parameter encodes org_id for the callback
    state = f"{org_id}:{uuid.uuid4().hex[:16]}"

    params = {
        "response_type": "code",
        "client_id": XERO_CLIENT_ID,
        "redirect_uri": XERO_REDIRECT_URI,
        "scope": XERO_SCOPES,
        "state": state,
    }

    auth_url = f"{XERO_AUTH_URL}?{urllib.parse.urlencode(params)}"
    logger.info(f"[XERO] Redirecting org={org_id} to Xero OAuth")
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def xero_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Xero OAuth callback. Exchanges code for tokens, stores connection.
    NOTE: This endpoint does NOT require JWT auth — Xero redirects here directly.
    The org_id is recovered from the state parameter.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error")

    if error:
        logger.error(f"[XERO] OAuth error: {error}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/dashboard?xero_error={error}"
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorisation code")

    # Extract org_id from state
    org_id = state.split(":")[0] if ":" in state else ""
    if not org_id:
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
            url=f"{FRONTEND_URL}/dashboard?xero_error=token_exchange_failed"
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
            url=f"{FRONTEND_URL}/dashboard?xero_error=connections_failed"
        )

    connections = conn_resp.json()
    if not connections:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/dashboard?xero_error=no_tenants"
        )

    # Use first tenant
    tenant = connections[0]
    tenant_id = tenant.get("tenantId", "")
    tenant_name = tenant.get("tenantName", "")

    # Upsert xero_connections (one connection per org)
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
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": token_expires_at,
            "scopes": XERO_SCOPES,
        }
    )
    await db.commit()

    logger.info(f"[XERO] Connected org={org_id} to tenant={tenant_name} ({tenant_id})")
    return RedirectResponse(
        url=f"{FRONTEND_URL}/dashboard?xero_connected=true"
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
    Sync financial data from Xero: P&L, Balance Sheet, and Chart of Accounts.
    Stores reports as JSONB in financial_data table.
    Syncs Chart of Accounts into account_mappings with auto-mapping.
    """
    org_id = _get_org_id(current_user)

    # Refresh tokens if needed
    creds = await _refresh_tokens_if_needed(db, org_id)
    access_token = creds["access_token"]
    tenant_id = creds["xero_tenant_id"]

    reports_synced = []
    now = datetime.now(timezone.utc)

    # --- Sync P&L Report ---
    try:
        async with httpx.AsyncClient() as client:
            pl_resp = await client.get(
                f"{XERO_API_BASE}/Reports/ProfitAndLoss",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Xero-Tenant-Id": tenant_id,
                    "Accept": "application/json",
                },
                params={"periods": "12", "timeframe": "MONTH"},
                timeout=30.0,
            )

        if pl_resp.status_code == 200:
            pl_data = pl_resp.json()
            # Get date range from report
            reports = pl_data.get("Reports", [])
            report_titles = reports[0].get("ReportTitles", []) if reports else []

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
                    "start": None,  # Xero report covers configurable range
                    "end": None,
                    "data": json.dumps(pl_data),
                    "fetched": now,
                }
            )
            reports_synced.append("ProfitAndLoss")
            logger.info(f"[XERO] P&L synced for org={org_id}")
        else:
            logger.error(f"[XERO] P&L fetch failed: {pl_resp.status_code}")
    except Exception as e:
        logger.error(f"[XERO] P&L sync error: {e}")

    # --- Sync Balance Sheet Report ---
    try:
        async with httpx.AsyncClient() as client:
            bs_resp = await client.get(
                f"{XERO_API_BASE}/Reports/BalanceSheet",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Xero-Tenant-Id": tenant_id,
                    "Accept": "application/json",
                },
                timeout=30.0,
            )

        if bs_resp.status_code == 200:
            bs_data = bs_resp.json()

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
                    "start": None,
                    "end": None,
                    "data": json.dumps(bs_data),
                    "fetched": now,
                }
            )
            reports_synced.append("BalanceSheet")
            logger.info(f"[XERO] Balance Sheet synced for org={org_id}")
        else:
            logger.error(f"[XERO] Balance Sheet fetch failed: {bs_resp.status_code}")
    except Exception as e:
        logger.error(f"[XERO] Balance Sheet sync error: {e}")

    # --- Sync Chart of Accounts into account_mappings ---
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

    mapping_complete = coa_stats["unmapped"] == 0

    return {
        "success": True,
        "reports_synced": reports_synced,
        "synced_at": now.isoformat(),
        "accounts_total": coa_stats["total"],
        "accounts_mapped": coa_stats["mapped"],
        "accounts_unmapped": coa_stats["unmapped"],
        "mapping_complete": mapping_complete,
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
        return {"success": True, "message": "No active Xero connection found"}

    # Attempt to revoke token (best effort)
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                XERO_CONNECTIONS_URL,
                headers={"Authorization": f"Bearer {row.access_token}"},
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