from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter()


# --- Request / Response Models ---


class VarianceInvestigateRequest(BaseModel):
    account_code: str
    account_name: str
    period_start: str        # YYYY-MM-DD
    period_end: str          # YYYY-MM-DD
    actual_amount: float
    budget_amount: float
    variance_amount: float   # actual - budget (signed)
    variance_pct: float      # percentage (signed)


class TransactionEvidence(BaseModel):
    type: str                # "transaction" | "invoice" | "journal"
    ref: str
    amount: float
    date: str                # YYYY-MM-DD


class VarianceFinding(BaseModel):
    description: str
    evidence: list[TransactionEvidence]
    driver_type: Literal[
        "new_supplier",
        "volume_change",
        "timing",
        "misclassification",
        "price_change",
        "other",
    ]


class AgentMetadata(BaseModel):
    tokens_used: int
    latency_ms: int
    xero_calls: int


class VarianceInvestigateResponse(BaseModel):
    request_id: str
    summary: str
    findings: list[VarianceFinding]
    confidence: Literal["high", "medium", "low"]
    suggested_actions: list[str]
    metadata: AgentMetadata


# --- Endpoint (stub — service layer built in Week 2) ---


@router.post(
    "/agents/variance-investigate",
    response_model=VarianceInvestigateResponse,
    summary="Investigate a variance in the AvB module",
    tags=["Agents"],
)
async def variance_investigate(
    request: VarianceInvestigateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Investigates a material variance for a given account and period.
    Fetches transaction-level data from Xero, analyses with Claude API,
    and returns structured findings with evidence.

    This endpoint is a stub. Full implementation ships in Week 2.
    """
    raise HTTPException(
        status_code=501,
        detail="Variance Investigator not yet implemented. Ships Week 2.",
    )
