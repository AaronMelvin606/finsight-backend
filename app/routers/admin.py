"""
FinSight AI - Admin Router
===========================
Protected administrative endpoints.
"""

import os
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.services.onboarding_service import run_onboarding

logger = logging.getLogger(__name__)

router = APIRouter()


class AllowlistRequest(BaseModel):
    email: str
    notes: Optional[str] = None


def _verify_admin_token(x_admin_token: str = Header(...)) -> str:
    """Validate the X-Admin-Token header against the ADMIN_TOKEN env var."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin token.",
        )
    return x_admin_token


@router.post("/admin/allowlist", status_code=status.HTTP_201_CREATED)
async def add_to_allowlist(
    payload: AllowlistRequest,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(_verify_admin_token),
):
    """Add an email to the registration allowlist."""
    email = payload.email.strip().lower()

    # Check for existing entry
    existing = await db.execute(
        text("SELECT email FROM registration_allowlist WHERE LOWER(email) = :email"),
        {"email": email},
    )
    if existing.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists in the allowlist.",
        )

    await db.execute(
        text(
            "INSERT INTO registration_allowlist (email, added_by, added_at, notes) "
            "VALUES (:email, 'admin-api', :added_at, :notes)"
        ),
        {
            "email": email,
            "added_at": datetime.utcnow(),
            "notes": payload.notes,
        },
    )
    await db.commit()

    logger.info(f"[ADMIN] Added {email} to registration allowlist")
    return {"email": email, "status": "added"}


@router.post("/admin/orgs/{org_id}/sync")
async def admin_sync_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(_verify_admin_token),
):
    """
    Trigger a Xero sync for any organisation by ID (admin-level, no user JWT required).
    Runs the same onboarding/sync pipeline as the initial Xero connect.
    """
    # Verify organisation exists
    org_check = await db.execute(
        text("SELECT id, name FROM organisations WHERE id = :org_id"),
        {"org_id": org_id},
    )
    org_row = org_check.fetchone()
    if not org_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation {org_id} not found.",
        )

    # Verify Xero connection exists
    xero_check = await db.execute(
        text(
            "SELECT id FROM xero_connections "
            "WHERE organisation_id = :org_id AND is_active = true"
        ),
        {"org_id": org_id},
    )
    if not xero_check.fetchone():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No active Xero connection for organisation {org_id}.",
        )

    # Trigger sync via onboarding pipeline (account mapping, FY rows, 24-month sync)
    try:
        result = await run_onboarding(db, org_id)
        logger.info(f"[ADMIN] Sync triggered for org={org_id} ({org_row.name})")
        return {
            "status": "ok",
            "org_id": org_id,
            "org_name": org_row.name,
            "message": "Sync completed successfully",
            "details": result,
        }
    except Exception as e:
        logger.error(f"[ADMIN] Sync failed for org={org_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        )
