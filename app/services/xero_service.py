"""
Xero credential service — shared authentication layer.
Used by: app/routers/integrations/xero.py, app/services/xero_queries.py
Extracted from xero.py private helper _refresh_tokens_if_needed()
on 11 April 2026 to support agent infrastructure (WS6).
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import HTTPException, status

from app.core.encryption import safe_decrypt, encrypt_token

logger = logging.getLogger(__name__)

XERO_TOKEN_URL = "https://identity.xero.com/connect/token"


async def get_valid_xero_credentials(
    db: AsyncSession,
    org_id: str,
    xero_client_id: str,
    xero_client_secret: str,
) -> dict:
    """
    Fetch active Xero credentials for an org, refreshing the access token
    if it is expired or within 5 minutes of expiry.

    Returns:
        dict with keys: access_token (str), xero_tenant_id (str), connection_id (str)

    Raises:
        HTTPException 404 — no active Xero connection found for org
        HTTPException 401 — token refresh failed (Xero rejected the refresh token)
    """
    result = await db.execute(
        text(
            "SELECT id, access_token, refresh_token, token_expires_at, xero_tenant_id "
            "FROM xero_connections "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"org_id": org_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active Xero connection found. Please connect Xero first.",
        )

    now = datetime.now(timezone.utc)
    if row.token_expires_at and row.token_expires_at > now + timedelta(minutes=5):
        return {
            "access_token": safe_decrypt(row.access_token),
            "xero_tenant_id": row.xero_tenant_id,
            "connection_id": str(row.id),
        }

    # Token expired or within 5 minutes of expiry — refresh
    logger.info(f"[XERO] Refreshing tokens for org={org_id}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": safe_decrypt(row.refresh_token),
                "client_id": xero_client_id,
                "client_secret": xero_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )

    if resp.status_code != 200:
        logger.error(
            f"[XERO] Token refresh failed for org={org_id}: "
            f"{resp.status_code} {resp.text}"
        )
        await db.execute(
            text("UPDATE xero_connections SET is_active = false WHERE id = :id"),
            {"id": str(row.id)},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Xero token refresh failed. Please reconnect Xero.",
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
        },
    )
    await db.commit()

    logger.info(f"[XERO] Tokens refreshed successfully for org={org_id}")
    return {
        "access_token": tokens["access_token"],
        "xero_tenant_id": row.xero_tenant_id,
        "connection_id": str(row.id),
    }
