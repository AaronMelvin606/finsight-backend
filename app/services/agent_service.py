"""
Agent orchestration service — WS6 Variance Investigator.
Handles the full lifecycle of an agent invocation:
  1. Write agent_requests row (status: pending)
  2. Update status to processing
  3. Fetch Xero data via xero_queries.py
  4. Call Claude API with structured prompt
  5. Parse and validate response
  6. Write agent_responses row
  7. Update agent_requests status to complete or failed

Service layer — no FastAPI concerns. All HTTPExceptions raised by
dependencies (xero_service, Claude API) are caught here, DB rows
updated to failed status, then re-raised as RuntimeError for the
router to translate.

Created: 11 April 2026 — WS6 Track B Week 2 build session.
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.services.xero_service import get_valid_xero_credentials
from app.services.xero_queries import (
    get_transactions_for_account,
    get_budget_for_account,
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET", "")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _create_agent_request(
    db: AsyncSession,
    org_id: str,
    user_id: str,
    input_params: dict,
) -> str:
    """
    Insert a new agent_requests row with status='pending'.
    Returns the new request UUID as a string.
    """
    request_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO agent_requests "
            "(id, organisation_id, user_id, agent_type, input_params, status, created_at) "
            "VALUES (:id, :org_id, :user_id, 'variance_investigator', "
            ":input_params, 'pending', now())"
        ),
        {
            "id": request_id,
            "org_id": org_id,
            "user_id": user_id,
            "input_params": json.dumps(input_params),
        },
    )
    await db.commit()
    logger.info(f"[AGENT] Created request {request_id} for org={org_id}")
    return request_id


async def _update_request_status(
    db: AsyncSession,
    request_id: str,
    status: str,
) -> None:
    """
    Update agent_requests.status. Sets completed_at when status is
    'complete' or 'failed'.
    Valid statuses: pending, processing, complete, failed.
    """
    completed_at = (
        datetime.now(timezone.utc)
        if status in ("complete", "failed")
        else None
    )
    await db.execute(
        text(
            "UPDATE agent_requests "
            "SET status = :status, completed_at = :completed_at "
            "WHERE id = :id"
        ),
        {
            "status": status,
            "completed_at": completed_at,
            "id": request_id,
        },
    )
    await db.commit()
    logger.info(f"[AGENT] Request {request_id} status → {status}")


async def _save_agent_response(
    db: AsyncSession,
    request_id: str,
    response_json: dict,
    confidence: str,
    tokens_used: int,
    latency_ms: int,
) -> None:
    """
    Insert a row into agent_responses.
    Called only after a successful Claude API response.
    """
    response_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO agent_responses "
            "(id, request_id, response_json, confidence, "
            "tokens_used, latency_ms, created_at) "
            "VALUES (:id, :request_id, :response_json, :confidence, "
            ":tokens_used, :latency_ms, now())"
        ),
        {
            "id": response_id,
            "request_id": request_id,
            "response_json": json.dumps(response_json),
            "confidence": confidence,
            "tokens_used": tokens_used,
            "latency_ms": latency_ms,
        },
    )
    await db.commit()
    logger.info(
        f"[AGENT] Saved response {response_id} for request {request_id} "
        f"tokens={tokens_used} latency={latency_ms}ms"
    )


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------


def _build_investigation_prompt(
    account_code: str,
    account_name: str,
    period_start: str,
    period_end: str,
    actual_amount: float,
    budget_amount: float,
    variance_amount: float,
    variance_pct: float,
    transactions: list[dict],
    budget_entries: list[dict],
) -> tuple[str, str]:
    """
    Build the system prompt and user message for the variance investigation.
    Returns (system_prompt, user_message).
    The system prompt instructs Claude to return pure JSON only.
    """
    system_prompt = """You are a financial analyst AI embedded in a CFO reporting platform.
Your task is to investigate an Actual vs Budget variance for a specific account.
You will be given transaction-level data from Xero and budget figures for the period.

You must respond with ONLY a valid JSON object. No preamble, no explanation, no markdown fences.
The JSON must exactly match this schema:
{
  "summary": "One sentence headline explanation of the variance",
  "findings": [
    {
      "description": "Specific finding with amounts and dates",
      "evidence": [
        {
          "type": "transaction",
          "ref": "transaction reference or supplier name",
          "amount": 0.00,
          "date": "YYYY-MM-DD"
        }
      ],
      "driver_type": "new_supplier | volume_change | timing | misclassification | price_change | other"
    }
  ],
  "confidence": "high | medium | low",
  "suggested_actions": [
    "Specific actionable recommendation"
  ]
}

Confidence rules:
- high: clear transaction evidence directly explains >80% of the variance
- medium: partial evidence, some interpretation required
- low: sparse data, cannot reliably explain the variance

Return at most 3 findings. Focus on material items only.
All amounts in GBP. All dates in YYYY-MM-DD format.
Findings must be grounded in the transaction data provided — do not speculate."""

    transaction_lines = "\n".join([
        f"  - {t['date']} | {t['source_name']} | {t['reference']} | £{t['amount']:,.2f}"
        for t in transactions[:50]  # cap at 50 to stay within context
    ]) or "  No transactions found for this period."

    budget_lines = "\n".join([
        f"  - {b['period']}: £{b['amount']:,.2f}"
        for b in budget_entries
    ]) or "  No budget data found for this period."

    user_message = f"""Investigate this Actual vs Budget variance:

Account: {account_code} — {account_name}
Period: {period_start} to {period_end}
Actual: £{actual_amount:,.2f}
Budget: £{budget_amount:,.2f}
Variance: £{variance_amount:,.2f} ({variance_pct:+.1f}%)

Transactions in Xero for this account and period:
{transaction_lines}

Budget breakdown by month:
{budget_lines}

Identify the top drivers of this variance and return your findings as JSON."""

    return system_prompt, user_message


async def _call_claude(
    system_prompt: str,
    user_message: str,
) -> tuple[dict, int]:
    """
    Call the Claude API and return (parsed_json_response, tokens_used).

    Raises:
        RuntimeError: network failure, non-200 status, or invalid JSON response
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 1500,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                },
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Claude API timed out after 60s: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Claude API network error: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"Claude API returned {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    tokens_used = data.get("usage", {}).get("output_tokens", 0)
    raw_text = data["content"][0]["text"]

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Claude response was not valid JSON: {exc}. "
            f"Raw response: {raw_text[:200]}"
        ) from exc

    # Validate required top-level keys
    required_keys = {"summary", "findings", "confidence", "suggested_actions"}
    missing = required_keys - set(parsed.keys())
    if missing:
        raise RuntimeError(
            f"Claude response missing required keys: {missing}. "
            f"Got: {list(parsed.keys())}"
        )

    # Validate confidence value
    if parsed.get("confidence") not in ("high", "medium", "low"):
        logger.warning(
            f"[AGENT] Claude returned unexpected confidence value: "
            f"{parsed.get('confidence')} — defaulting to low"
        )
        parsed["confidence"] = "low"

    return parsed, tokens_used


# ---------------------------------------------------------------------------
# Main orchestration entry point
# ---------------------------------------------------------------------------


async def orchestrate_variance_investigation(
    db: AsyncSession,
    org_id: str,
    user_id: str,
    account_code: str,
    account_name: str,
    period_start: str,
    period_end: str,
    actual_amount: float,
    budget_amount: float,
    variance_amount: float,
    variance_pct: float,
) -> dict:
    """
    Full lifecycle orchestration for a variance investigation agent request.

    Creates DB audit rows, fetches Xero data, calls Claude, saves response.
    Always updates agent_requests.status before returning or raising.
    Never leaves orphaned 'pending' rows.

    Returns:
        dict matching VarianceInvestigateResponse schema (without request_id —
        caller adds that after receiving the return value)

    Raises:
        RuntimeError: any unrecoverable failure — status set to 'failed' in DB
        fastapi.HTTPException: propagated from get_valid_xero_credentials if
            no active Xero connection exists (404) or token refresh fails (401)
    """
    start_time = time.monotonic()
    xero_calls = 0

    input_params = {
        "account_code": account_code,
        "account_name": account_name,
        "period_start": period_start,
        "period_end": period_end,
        "actual_amount": actual_amount,
        "budget_amount": budget_amount,
        "variance_amount": variance_amount,
        "variance_pct": variance_pct,
    }

    # Step 1 — create audit row
    request_id = await _create_agent_request(db, org_id, user_id, input_params)

    try:
        # Step 2 — mark as processing
        await _update_request_status(db, request_id, "processing")

        # Step 3 — get Xero credentials (may raise HTTPException — let it propagate)
        creds = await get_valid_xero_credentials(
            db, org_id, XERO_CLIENT_ID, XERO_CLIENT_SECRET
        )
        access_token = creds["access_token"]
        xero_tenant_id = creds["xero_tenant_id"]

        # Step 4 — fetch Xero data
        transactions = await get_transactions_for_account(
            access_token, xero_tenant_id,
            account_code, period_start, period_end,
        )
        xero_calls += 1

        budget_entries = await get_budget_for_account(
            access_token, xero_tenant_id,
            account_code, period_start, period_end,
        )
        # get_budget_for_account makes 1 list call + N detail calls
        # N is unknown without inspecting response — log as minimum 1
        xero_calls += 1

        logger.info(
            f"[AGENT] request={request_id} "
            f"transactions={len(transactions)} "
            f"budget_entries={len(budget_entries)}"
        )

        # Step 5 — handle empty transaction data
        if not transactions:
            logger.info(
                f"[AGENT] No transactions found for request={request_id} "
                f"— returning insufficient data response"
            )
            latency_ms = int((time.monotonic() - start_time) * 1000)
            empty_response = {
                "summary": (
                    f"No transactions found in Xero for account "
                    f"{account_code} ({account_name}) "
                    f"between {period_start} and {period_end}. "
                    f"The variance cannot be investigated without transaction data."
                ),
                "findings": [],
                "confidence": "low",
                "suggested_actions": [
                    "Verify transactions are recorded in Xero for this account and period.",
                    "Check that the Xero account code matches the expected account.",
                ],
            }
            await _save_agent_response(
                db, request_id, empty_response, "low", 0, latency_ms
            )
            await _update_request_status(db, request_id, "complete")
            return {**empty_response, "request_id": request_id,
                    "metadata": {"tokens_used": 0,
                                 "latency_ms": latency_ms,
                                 "xero_calls": xero_calls}}

        # Step 6 — build prompt and call Claude
        system_prompt, user_message = _build_investigation_prompt(
            account_code, account_name,
            period_start, period_end,
            actual_amount, budget_amount,
            variance_amount, variance_pct,
            transactions, budget_entries,
        )

        claude_response, tokens_used = await _call_claude(
            system_prompt, user_message
        )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Step 7 — save response and mark complete
        await _save_agent_response(
            db, request_id,
            claude_response,
            claude_response["confidence"],
            tokens_used,
            latency_ms,
        )
        await _update_request_status(db, request_id, "complete")

        logger.info(
            f"[AGENT] request={request_id} complete "
            f"confidence={claude_response['confidence']} "
            f"tokens={tokens_used} latency={latency_ms}ms"
        )

        return {
            **claude_response,
            "request_id": request_id,
            "metadata": {
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
                "xero_calls": xero_calls,
            },
        }

    except Exception as exc:
        # Mark as failed before re-raising — never leave orphaned pending rows
        logger.error(
            f"[AGENT] request={request_id} failed: {type(exc).__name__}: {exc}"
        )
        try:
            await _update_request_status(db, request_id, "failed")
        except Exception as db_exc:
            logger.error(
                f"[AGENT] Could not update failed status for "
                f"request={request_id}: {db_exc}"
            )
        raise
