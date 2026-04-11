"""
Reusable Xero query library — shared across all FinSight AI agent types.
All functions accept credentials as parameters (injected by agent_service.py).
All functions return standardised dicts — no FastAPI or DB concerns here.

Endpoints used:
  - GET /Reports/AccountTransactions  (accounting.reports.read scope)
  - GET /Budgets + GET /Budgets/{id}  (accounting.budgets.read scope)

Both scopes are present in XERO_SCOPES since WS1 (commit 18b3171).
Created: 11 April 2026 — WS6 Track B Week 2 build session.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

XERO_API_BASE = "https://api.xero.com/api.xro/2.0"

# Timeout constants
_DATA_TIMEOUT = 30.0
_AUTH_TIMEOUT = 15.0


def _build_headers(access_token: str, xero_tenant_id: str) -> dict:
    """Build standard Xero API request headers."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Xero-Tenant-Id": xero_tenant_id,
        "Accept": "application/json",
    }


async def get_transactions_for_account(
    access_token: str,
    xero_tenant_id: str,
    account_code: str,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """
    Fetch all ledger transactions for a specific account code and date range.

    Uses GET /Reports/AccountTransactions — returns all movements through
    a given account for the period, suitable for variance investigation.

    Args:
        access_token:    Decrypted Xero Bearer token from get_valid_xero_credentials()
        xero_tenant_id:  Xero tenant identifier for the connected org
        account_code:    Xero account code (e.g. "200", "400")
        period_start:    ISO date string "YYYY-MM-DD" — inclusive start
        period_end:      ISO date string "YYYY-MM-DD" — inclusive end

    Returns:
        List of standardised transaction dicts. Empty list if no transactions
        found or if Xero returns an unexpected response. Never raises on
        empty data — caller must handle empty list explicitly.

    Raises:
        httpx.TimeoutException:  Xero API did not respond within 30s
        httpx.HTTPError:         Network-level failure
        ValueError:              Xero returned non-200 status
    """
    url = f"{XERO_API_BASE}/Reports/AccountTransactions"
    params = {
        "fromDate": period_start,
        "toDate": period_end,
        "accountCode": account_code,
    }

    logger.info(
        f"[XERO-QUERY] get_transactions_for_account: "
        f"account={account_code} period={period_start}→{period_end}"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers=_build_headers(access_token, xero_tenant_id),
            params=params,
            timeout=_DATA_TIMEOUT,
        )

    if resp.status_code != 200:
        logger.error(
            f"[XERO-QUERY] AccountTransactions failed: "
            f"status={resp.status_code} account={account_code} "
            f"body={resp.text[:200]}"
        )
        raise ValueError(
            f"Xero AccountTransactions returned {resp.status_code} "
            f"for account {account_code}"
        )

    data = resp.json()

    # Xero Reports API wraps results in Reports[].Rows[].Cells[]
    # We normalise to a flat list of transaction dicts
    transactions = []
    reports = data.get("Reports", [])
    if not reports:
        logger.info(
            f"[XERO-QUERY] No reports returned for account={account_code}"
        )
        return []

    report = reports[0]
    rows = report.get("Rows", [])

    for section in rows:
        if section.get("RowType") != "Section":
            continue
        for row in section.get("Rows", []):
            if row.get("RowType") != "Row":
                continue
            cells = row.get("Cells", [])
            if len(cells) < 5:
                continue
            try:
                transactions.append({
                    "date": cells[0].get("Value", ""),
                    "source_type": cells[1].get("Value", ""),
                    "source_name": cells[2].get("Value", ""),
                    "reference": cells[3].get("Value", ""),
                    "amount": _parse_amount(cells[4].get("Value", "0")),
                    "account_code": account_code,
                })
            except (IndexError, KeyError) as e:
                logger.warning(
                    f"[XERO-QUERY] Skipping malformed transaction row: {e}"
                )
                continue

    logger.info(
        f"[XERO-QUERY] get_transactions_for_account: "
        f"found {len(transactions)} transactions for account={account_code}"
    )
    return transactions


async def get_budget_for_account(
    access_token: str,
    xero_tenant_id: str,
    account_code: str,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """
    Fetch budget figures for a specific account code and date range.

    Uses GET /Budgets (list) then GET /Budgets/{id} (detail) to extract
    BudgetLines for the given account code. Matches the pattern used by
    the existing xero_sync_budgets() endpoint.

    Args:
        access_token:    Decrypted Xero Bearer token
        xero_tenant_id:  Xero tenant identifier
        account_code:    Xero account code (e.g. "200", "400")
        period_start:    "YYYY-MM-DD" — filter BudgetBalances to this range
        period_end:      "YYYY-MM-DD" — filter BudgetBalances to this range

    Returns:
        List of dicts: [{"period": "YYYY-MM", "amount": float, "account_code": str}]
        Empty list if no budget found for this account — caller handles explicitly.

    Raises:
        httpx.TimeoutException:  Xero API did not respond within 30s
        httpx.HTTPError:         Network-level failure
        ValueError:              Xero returned non-200 on list or detail call
    """
    headers = _build_headers(access_token, xero_tenant_id)
    start_month = period_start[:7]  # "YYYY-MM"
    end_month = period_end[:7]      # "YYYY-MM"

    logger.info(
        f"[XERO-QUERY] get_budget_for_account: "
        f"account={account_code} period={start_month}→{end_month}"
    )

    # Step 1 — fetch budget list
    async with httpx.AsyncClient() as client:
        list_resp = await client.get(
            f"{XERO_API_BASE}/Budgets",
            headers=headers,
            timeout=_DATA_TIMEOUT,
        )

    if list_resp.status_code != 200:
        logger.error(
            f"[XERO-QUERY] Budget list failed: status={list_resp.status_code}"
        )
        raise ValueError(
            f"Xero Budgets list returned {list_resp.status_code}"
        )

    budgets = list_resp.json().get("Budgets", [])
    if not budgets:
        logger.info("[XERO-QUERY] No budgets found in Xero")
        return []

    # Step 2 — fetch detail for each budget, extract matching lines
    budget_entries: list[dict] = []

    async with httpx.AsyncClient() as client:
        for budget_summary in budgets:
            budget_id = budget_summary.get("BudgetID")
            if not budget_id:
                continue

            detail_resp = await client.get(
                f"{XERO_API_BASE}/Budgets/{budget_id}",
                headers=headers,
                timeout=_DATA_TIMEOUT,
            )

            if detail_resp.status_code != 200:
                logger.warning(
                    f"[XERO-QUERY] Budget detail failed for "
                    f"budget_id={budget_id}: {detail_resp.status_code}"
                )
                continue

            budget_detail = detail_resp.json().get("Budgets", [])
            for budget in budget_detail:
                for line in budget.get("BudgetLines", []):
                    if line.get("AccountCode", "") != account_code:
                        continue
                    for bal in line.get("BudgetBalances", []):
                        period_raw = bal.get("Period", "")
                        period = period_raw[:7]  # "YYYY-MM"
                        if not (start_month <= period <= end_month):
                            continue
                        amount = bal.get("Amount")
                        if amount is None:
                            continue
                        budget_entries.append({
                            "period": period,
                            "amount": float(amount),
                            "account_code": account_code,
                        })

    logger.info(
        f"[XERO-QUERY] get_budget_for_account: "
        f"found {len(budget_entries)} budget entries for account={account_code}"
    )
    return budget_entries


def _parse_amount(value: str) -> float:
    """
    Parse a Xero amount string to float.
    Handles empty strings, parentheses for negatives e.g. "(1,234.56)",
    and comma-separated thousands.
    Returns 0.0 on any parse failure — never raises.
    """
    if not value or value.strip() == "":
        return 0.0
    cleaned = value.strip().replace(",", "")
    # Xero uses parentheses for negative amounts in report cells
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"[XERO-QUERY] Could not parse amount: '{value}'")
        return 0.0
