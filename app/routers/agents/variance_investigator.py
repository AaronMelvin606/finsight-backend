from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.services.agent_service import orchestrate_variance_investigation

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


# --- Endpoint ---


@router.post(
    "/agents/variance-investigate",
    response_model=VarianceInvestigateResponse,
    summary="Investigate a variance in the AvB module",
    tags=["Agents"],
)
@limiter.limit("5/minute")
async def variance_investigate(
    http_request: Request,
    body: VarianceInvestigateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Investigates a material variance for a given account and period.
    Fetches transaction-level data from Xero, analyses with Claude API,
    and returns structured findings with evidence.

    Rate limited: 5 requests per minute per IP.
    Typical latency: 5-15 seconds (Xero fetch + Claude API).
    """
    if not current_user.active_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation. Please connect a Xero account to continue.",
        )

    org_id = str(current_user.active_org_id)
    user_id = str(current_user.id)

    try:
        result = await orchestrate_variance_investigation(
            db=db,
            org_id=org_id,
            user_id=user_id,
            account_code=body.account_code,
            account_name=body.account_name,
            period_start=body.period_start,
            period_end=body.period_end,
            actual_amount=body.actual_amount,
            budget_amount=body.budget_amount,
            variance_amount=body.variance_amount,
            variance_pct=body.variance_pct,
        )
        return result

    except HTTPException:
        # Re-raise HTTPExceptions from xero_service (404 no connection, 401 token refresh)
        raise
    except RuntimeError as exc:
        # Service layer failures — translate to 500
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Investigation failed: {exc}",
        ) from exc
