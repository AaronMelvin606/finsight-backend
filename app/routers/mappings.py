from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional

from app.core.database import AsyncSessionLocal
from app.api.deps import get_current_user

router = APIRouter()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


class MappingUpdate(BaseModel):
    reporting_category: str
    reporting_subcategory: Optional[str] = None


@router.get("/mappings")
async def list_mappings(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT id, account_code, account_name, account_type,
                   reporting_category, reporting_subcategory, is_mapped,
                   created_at, updated_at
            FROM account_mappings
            WHERE organisation_id = :org_id
            ORDER BY account_code
        """),
        {"org_id": org_id},
    )
    rows = result.mappings().all()
    return {"mappings": [dict(r) for r in rows]}


@router.get("/mappings/unmapped")
async def list_unmapped(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT id, account_code, account_name, account_type
            FROM account_mappings
            WHERE organisation_id = :org_id
              AND (is_mapped = FALSE OR reporting_category IS NULL OR reporting_category = '')
            ORDER BY account_code
        """),
        {"org_id": org_id},
    )
    rows = result.mappings().all()
    return {"unmapped": [dict(r) for r in rows]}


@router.patch("/mappings/{account_code}")
async def update_mapping(
    account_code: str,
    payload: MappingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            UPDATE account_mappings
            SET reporting_category    = :reporting_category,
                reporting_subcategory = :reporting_subcategory,
                is_mapped             = TRUE,
                updated_at            = now()
            WHERE organisation_id = :org_id
              AND account_code    = :account_code
            RETURNING id
        """),
        {
            "org_id": org_id,
            "account_code": account_code,
            "reporting_category": payload.reporting_category,
            "reporting_subcategory": payload.reporting_subcategory,
        },
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Account mapping not found")
    return {"message": "Mapping updated", "account_code": account_code}


@router.get("/mappings/summary")
async def mapping_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    org_id = current_user["organisation_id"]
    result = await db.execute(
        text("""
            SELECT
                COUNT(*)                                         AS total,
                COUNT(*) FILTER (WHERE is_mapped = TRUE)        AS mapped,
                COUNT(*) FILTER (WHERE is_mapped = FALSE
                    OR reporting_category IS NULL
                    OR reporting_category = '')                  AS unmapped
            FROM account_mappings
            WHERE organisation_id = :org_id
        """),
        {"org_id": org_id},
    )
    row = result.mappings().fetchone()
    return dict(row)
