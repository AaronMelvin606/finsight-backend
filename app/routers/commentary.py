"""
FinSight AI - Commentary Router
================================
Backend proxy for Claude AI commentary generation.
Moves all Anthropic API calls from the frontend to the backend.
"""

import json
import logging
import os
import time
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.organisation import Organisation
from app.models.user import User
from app.services.budget_service import get_budget_status

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Valid modules and their system prompts
# ---------------------------------------------------------------------------

VALID_MODULES = {
    "executive_summary",
    "actual_vs_budget",
    "revenue_summary",
    "scenario_planning",
}

CFO_SYSTEM_PROMPT = (
    "You are a senior CFO advisor producing boardroom-quality executive commentary "
    "for a finance dashboard. Respond ONLY with a valid JSON object — no preamble, "
    "no markdown fences, no additional text. Use British English. Be direct and "
    "specific. Avoid generic statements. Do not repeat numbers already visible in "
    "the KPI tiles.\n"
    'Format: {"summary":"...","revenue":"...","opex":"...","outlook":"...","strategic":"..."}\n'
    "summary: 2-3 sentences of high-level narrative on overall business performance "
    "and the headline variance versus budget. What do the numbers mean for the "
    "business, not what the numbers are.\n"
    "revenue: one sentence on revenue performance direction only — ahead or behind "
    "budget, accelerating or decelerating.\n"
    "opex: one sentence on cost discipline — are costs controlled or are there "
    "concerning overruns.\n"
    "outlook: one sentence forward-looking view for the next 90 days based on "
    "current trajectory.\n"
    "strategic: the single most important decision or action the leadership team "
    "should take this period."
)

VARIANCE_SYSTEM_PROMPT = (
    "You are a finance director producing a variance analysis commentary for a "
    "management accounts review. Respond ONLY with a valid JSON object — no preamble, "
    "no markdown fences, no additional text. Use British English. Be direct and "
    "specific. Name the categories. Use the actual variance figures provided.\n"
    'Format: {"summary":"...","topDriver":"...","outlook":"...","riskAction":"..."}\n'
    "summary: one sentence stating the overall AvB position — is the business ahead "
    "or behind budget and by how much.\n"
    "topDriver: the single biggest variance driver this period — name the specific "
    "category and the variance amount. Explain the likely operational cause.\n"
    "outlook: the forward-looking implication of the current variance trajectory — "
    "what happens if this trend continues.\n"
    "riskAction: the most important management action needed — be specific about "
    "what should be done and why."
)

REVENUE_SYSTEM_PROMPT = (
    "You are a commercial finance analyst producing a revenue performance commentary. "
    "Respond ONLY with a valid JSON object — no preamble, no markdown fences, no "
    "additional text. Use British English. Be direct and specific. Focus entirely on "
    "revenue — do not mention costs, margins, or EBITDA.\n"
    'Format: {"summary":"...","topDriver":"...","outlook":"...","riskAction":"..."}\n'
    "summary: one sentence on YTD revenue performance versus budget — ahead or "
    "behind and by how much.\n"
    "topDriver: the top revenue driver by account this period — name it specifically "
    "and state whether it is performing in line with expectations or is an anomaly.\n"
    "outlook: the forward-looking revenue view for the next 60-90 days — is the "
    "current trajectory sustainable.\n"
    "riskAction: the key revenue risk or action — what could derail revenue "
    "performance and what should be done about it."
)

SCENARIO_SYSTEM_PROMPT = (
    "You are a senior CFO advisor producing scenario planning commentary for a "
    "finance dashboard.\n"
    "Respond ONLY with a valid JSON object — no preamble, no markdown fences, no "
    "additional text.\n"
    "Use British English. Be direct and specific. Respond to the scenario "
    "adjustments provided.\n"
    'Format: {"summary":"...","revenue":"...","opex":"...","outlook":"...","strategic":"..."}\n'
    "summary: overall scenario assessment. revenue: revenue impact of adjustments. "
    "opex: cost impact of adjustments. outlook: 90-day outlook under this scenario. "
    "strategic: recommended action or decision given this scenario."
)

MODULE_PROMPTS = {
    "executive_summary": CFO_SYSTEM_PROMPT,
    "actual_vs_budget": VARIANCE_SYSTEM_PROMPT,
    "revenue_summary": REVENUE_SYSTEM_PROMPT,
    "scenario_planning": SCENARIO_SYSTEM_PROMPT,
}

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CommentaryRequest(BaseModel):
    module: str
    context: str
    period_start: str | None = None
    period_end: str | None = None

    @field_validator("module")
    @classmethod
    def validate_module(cls, v: str) -> str:
        if v not in VALID_MODULES:
            raise ValueError(
                f"Invalid module '{v}'. Must be one of: {', '.join(sorted(VALID_MODULES))}"
            )
        return v


class CommentaryResponse(BaseModel):
    commentary: dict
    module: str
    generated_at: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"


@router.post("/commentary/generate", response_model=CommentaryResponse)
async def generate_commentary(
    body: CommentaryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate AI commentary for a given finance module."""

    org_id = str(current_user.active_org_id) if current_user.active_org_id else "unknown"

    # --- Budget boundary check (AvB module only) ---
    if body.module == "actual_vs_budget" and current_user.active_org_id:
        fy_start_month = 4
        if body.period_start:
            ref_date = date.fromisoformat(body.period_start)
        else:
            ref_date = date.today()
        fy_year = ref_date.year if ref_date.month >= fy_start_month else ref_date.year - 1
        fy_s = date(fy_year, fy_start_month, 1)
        fy_e = date(fy_year + 1, fy_start_month, 1) - timedelta(days=1)
        budget_status = await get_budget_status(db, org_id, fy_s, fy_e)
        if budget_status == "no_budget":
            logger.info(
                "Commentary skipped — no budget | module=%s org=%s",
                body.module, org_id,
            )
            return CommentaryResponse(
                commentary={
                    "skip": True,
                    "reason": "no_budget",
                    "message": "No budget found for the current financial year. "
                               "Upload a budget, sync from Xero, or generate one "
                               "from prior year actuals to enable AI commentary.",
                },
                module=body.module,
                generated_at=datetime.utcnow().isoformat(),
            )

    # --- Check API key ---
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set — cannot generate commentary")
        raise HTTPException(
            status_code=503,
            detail="AI commentary service unavailable — ANTHROPIC_API_KEY not configured",
        )

    system_prompt = MODULE_PROMPTS[body.module]

    if current_user.active_org_id:
        try:
            res = await db.execute(
                select(Organisation.org_context).where(
                    Organisation.id == current_user.active_org_id
                )
            )
            org_context = res.scalar_one_or_none()
            if org_context and str(org_context).strip():
                system_prompt = (
                    f"{system_prompt}\n\nContext about this business: "
                    f"{str(org_context).strip()}"
                )
        except Exception:
            logger.exception(
                "Skipping org_context for commentary | org=%s module=%s",
                org_id,
                body.module,
            )

    # --- Call Anthropic API ---
    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 1000,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": body.context}],
                },
            )
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "Anthropic API request failed | module=%s org=%s elapsed_ms=%.0f error=%s",
            body.module, org_id, elapsed_ms, str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail=f"AI commentary service unavailable — upstream request failed: {exc}",
        )

    elapsed_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        logger.error(
            "Anthropic API non-200 | module=%s org=%s status=%d elapsed_ms=%.0f body=%s",
            body.module, org_id, resp.status_code, elapsed_ms, resp.text[:500],
        )
        raise HTTPException(
            status_code=503,
            detail=f"AI commentary service returned status {resp.status_code}",
        )

    # --- Parse response ---
    data = resp.json()
    raw_text = data["content"][0]["text"]

    try:
        commentary = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error(
            "Claude response JSON parse failed | module=%s org=%s raw=%s",
            body.module, org_id, raw_text[:500],
        )
        raise HTTPException(
            status_code=422,
            detail=f"AI response was not valid JSON: {exc}. Raw text: {raw_text[:500]}",
        )

    logger.info(
        "Commentary generated | module=%s org=%s elapsed_ms=%.0f",
        body.module, org_id, elapsed_ms,
    )

    return CommentaryResponse(
        commentary=commentary,
        module=body.module,
        generated_at=datetime.utcnow().isoformat(),
    )
