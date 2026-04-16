# FinSight AI — Backend (finsight-backend)

## What this repo is
FastAPI backend for FinSight AI — a modular SaaS CFO platform. Deployed on Google Cloud Run at api.finsightai.tech.

## Infrastructure
- Runtime: FastAPI on Google Cloud Run (us-central1)
- Production revision: finsight-backend-00207-bnq (deployed 16 Apr 2026)
- Previous production revision: finsight-backend-00206-qbh (deployed 16 Apr 2026)
- Staging revision: finsight-backend-staging-00038-q9f (deployed 16 Apr 2026)
- Database: Neon PostgreSQL (11 tables — agent_requests + agent_responses added 11 Apr 2026)
- Custom domain: api.finsightai.tech → finsight-backend-520129376224.us-central1.run.app
- Monitoring: Sentry (backend DSN), GCP Monitoring alerts
- Analytics: PostHog (eu.posthog.com)

## Neon tables
users, organisations, xero_connections, account_mappings, budget_monthly, fiscal_years, fiscal_year_months, financial_line_items, registration_allowlist, organisation_members, agent_requests, agent_responses

## Sandbox constants
- Org ID: 2a291c1b-926e-4e2f-9dfa-5fc717960b4c
- Sandbox login: aaron@finsightai.tech / FinSight2026!

## API login (curl / scripts)
- Use **`POST /api/v1/auth/login/json`** with JSON `{"email","password"}` for programmatic login and JWT retrieval.
- **`POST /api/v1/auth/login`** is OAuth2 form (`username` / `password`), not JSON — do not use it for JSON bodies.

## Non-negotiable rules
- All KPI calculations live in the backend. Never move calculations to the frontend.
- Budget ingestion: Path A (Xero GET /budgets) is always preferred. Path B (CSV upload) is the fallback. Path C (POST /budgets/generate-from-actuals) auto-drafts from prior year actuals.
- getDefaultPeriodEnd() must return the last day of the previous completed month — never today's date.
- Period labels must be human-readable e.g. "Apr 2025 — Feb 2026" — never ISO strings.
- UK FY convention: FY year = calendar year of start month. April 2025–March 2026 = FY25.
- Always use "AvB" (Actual vs Budget) — never "BvA". All variables, labels, and comments use avb / actualVsBudget.
- Accounting sign conventions throughout. Literal £ symbol — never Unicode escapes. British English throughout.
- Finance numbers must always reconcile before any commit is approved.

## Reconciled demo numbers (Xero Demo Company, as of Mar 2026)
Revenue £36,284 − COGS £1,950 = GP £34,334; GP − OpEx £17,622 = EBITDA £16,712

## Build methodology
- Always show current code before any fix.
- Verify changes with sed -n or grep — never from summaries.
- Never accept "cache issue" or "code is correct as-is" without investigation.
- Never commit without seeing the exact diff.
- Never combine separate tasks under one commit.
- Run verification scripts post-deploy.
- At the start of every session: git pull origin main before writing any code.

## Security

### GCP Secret Manager — current state (16 Apr 2026)
All secrets except XERO_CLIENT_ID are now in Secret Manager:

| Secret | Status |
|---|---|
| SECRET_KEY | ✅ Secret Manager |
| BASE_URL | ✅ Secret Manager |
| ANTHROPIC_API_KEY | ✅ Secret Manager |
| DATABASE_URL | ✅ Secret Manager |
| XERO_CLIENT_SECRET | ✅ Secret Manager |
| ADMIN_TOKEN | ✅ Secret Manager |
| RESEND_API_KEY | ✅ Secret Manager |
| XERO_TOKEN_ENCRYPTION_KEY | ✅ Secret Manager (xero-token-encryption-key:2) — F3b complete 16 Apr 2026 |
| XERO_CLIENT_ID | ⚠️ Still plaintext — lower priority |

### Secret Manager v1 — scheduled destroy 23–30 Apr 2026
F3b complete. v1 disabled 16 Apr 2026. All xero_connections rows re-encrypted to v2. Zero plaintext tokens remain in production.
Destroy command when ready (after 7–14 day soak):
```bash
gcloud secrets versions destroy 1 --secret=xero-token-encryption-key --project gen-lang-client-0798522650
```

### Security tiers
- Tier 1 complete: all critical secrets in GCP Secret Manager (F1–F2, F4–F8 + C1: 9 Apr 2026 · F3 delivery swap: 14 Apr 2026 · F3b real rotation: 16 Apr 2026)
- Tier 2 complete: GCP Monitoring 401 spike alerts, slowapi rate limiting on /auth/register and /auth/login
- Tier 3 pending (post first customer): audit_log table, failed login lockout, split Cloud Run service accounts per environment
- Rate limiting: app/core/limiter.py

## Key commits (for reference)
- bce2b33: FY staleness fix
- 7535dd6: dynamic registration allowlist
- 346159e: unmapped account dropdown
- faa76c6 + d1e9bed: login/register toggle
- 4a676ea: privacy/cookie policy
- 4ac35f0: completed-periods endpoint, close-period via fiscal_year_months, generate_fy_rows refresh
- 686ecc5: completed-periods — read month_number (not month_index)
- 5ab70b5: initial Xero sync 24 months (prior-year comparison)
- eb2c877: FY rollover backend fixes merged staging → main (3 Apr 2026)

## Environments (added 28 Mar 2026)

### Two environments — both live

| Environment | Backend | Frontend | Neon |
|-------------|---------|----------|------|
| Production | api.finsightai.tech | finsightai-dashboard.netlify.app | production project (sweet-pine-82812474) |
| Staging | api-staging.finsightai.tech | finsightai-dashboard-staging.netlify.app | separate staging project |

- Staging Netlify site ID: 3ceb45c6-3185-4d36-b494-a4005f41b1de
- Production Netlify site ID: 6fdc9225-d3d2-417f-a11d-3c604f2816eb
- Staging Cloud Run service: finsight-backend-staging (us-central1)
- Production Cloud Run service: finsight-backend (us-central1)
- GCP project ID: **gen-lang-client-0798522650** — not `finsight-ai`. All `gcloud` commands must use `--project gen-lang-client-0798522650`.

### DNS known issue
Home WiFi/ISP blocks .run.app domains — use mobile hotspot for all curl
verification against api.finsightai.tech and api-staging.finsightai.tech.
Direct Cloud Run URL always works regardless of network:
finsight-backend-staging-520129376224.us-central1.run.app

### Staging traffic routing — FIXED 16 Apr 2026
Staging was pinned to named revision `finsight-backend-staging-00034-8lq` (discovered 14 Apr 2026). Fixed during F3b Step 5 via `--to-latest`. Staging now uses `latestRevision: true` — new revisions auto-promote correctly.
Current staging revision: `finsight-backend-staging-00038-q9f`

### Deployment flow
Normal:  feature branch → staging → verify → merge to main → production
Hotfix:  hotfix branch → main → verify in production → merge back to staging

### Keeping environments in sync after hotfixes
Run in finsight-backend:
  git checkout staging && git merge main && git push origin staging && git checkout main
Run in FinSight-AI---Professional-Growth-Suite:
  git checkout staging && git merge main && git push origin staging && git checkout main

### gcloud describe safety rule (added 14 Apr 2026)
Before running `--format=json` on any Cloud Run service spec, filter out env var values to avoid printing secrets to transcript:

```bash
gcloud run services describe SERVICE --format=json | jq 'del(.. | .value?)'
```

Never dump raw Cloud Run JSON without this filter when plaintext env vars may exist.

### gcloud secrets flag — important distinction (added 16 Apr 2026)
`--remove-env-vars` only removes plain env vars. It does NOT remove secret-mounted vars set via `--update-secrets`.
To remove a secret-mounted env var, use `--remove-secrets`:
```bash
gcloud run services update SERVICE --remove-secrets ENV_VAR_NAME
```
Using the wrong flag silently no-ops — no warning is printed.

---

## fiscal_year_months table (added 28 Mar 2026)

- month_period is VARCHAR stored as YYYY-MM in production
- NEVER use month_period::date — breaks on YYYY-MM format
- ALWAYS use _MONTH_END_EXPR / _MONTH_END_SQL from fiscal_year_service.py
  which handles both YYYY-MM and YYYY-MM-DD via explicit CASE branches
- Columns: organisation_id, fy_year, month_period, is_completed,
  is_closed, closed_at, closed_by (text)
- NO start_date / end_date / fiscal_year_id columns on this table

## Period close architecture (30 Mar 2026)

- Period close is **two-tier**: **`is_completed`** (automatic — all past months marked complete on Xero connect and on every **`GET /reports/completed-periods`** call) and **`is_closed`** (manual sign-off, optional user action). **`is_completed`** drives module rendering. **`is_closed`** is additive.
- **`ensure_fiscal_months_current()`** only sets **`is_completed = true`**, never false. Called at the top of **`GET /reports/completed-periods`**.
- **`generate_fy_rows()`** runs an **UPDATE** after **INSERT** that refreshes stale **`is_completed = false`** rows for past months.
- Initial Xero sync pulls **24 months** of history (not 12) so Revenue Summary can compare to the prior year.

## GET /reports/available-fys (3 Apr 2026)

- Returns list of financial years for the authenticated user's org
- Response fields per FY: fy_year, fy_label, fy_start, fy_end, is_current, has_data
- Only shows FYs from the fiscal_years table
- has_data checks financial_line_items existence within the FY date range
- Used by frontend FY selector dropdown

## GET /reports/completed-periods (30 Mar 2026)

- **`total_completed`** and **`latest_completed`** are scoped to the **current FY only**.
- The **`completed_periods`** array lists completed months across **all FYs** (full history).

## Multi-org architecture (live 5 April 2026)

- Junction table: organisation_members (user_id, organisation_id, role)
- New column: users.active_org_id (UUID FK → organisations.id)
- All endpoints resolve org from active_org_id (not organisation_id)
- users.organisation_id kept as deprecated legacy column — do not drop
- New endpoints: GET /auth/my-orgs, POST /auth/switch-org
- New admin endpoint: POST /admin/orgs/{org_id}/sync (X-Admin-Token)
- Xero OAuth callback supports multi-org: creates new org on additional connect
- Dedup guard: returns xero_error=already_connected if tenant already linked

## organisation_members table (added 28 Mar 2026)

- Columns: id (uuid), organisation_id, user_id, role, invited_by_id,
  invitation_token, invitation_accepted_at, joined_at
- NO created_at column — use joined_at
- Sandbox row inserted 28 Mar 2026:
  user_id=d019c93f-2094-40c1-a29c-f157bfb91b5a
  org_id=2a291c1b-926e-4e2f-9dfa-5fc717960b4c
  role=owner

## GET /organisations/me (added 28 Mar 2026)

- Route MUST be registered before GET /{org_id} to prevent "me" being
  treated as a UUID and crashing the DB query
- Resolves org in order: (1) fresh DB lookup on users.active_org_id,
  (2) in-memory current_user.organisation_id, (3) organisation_members row
- get_organisation allows access if no membership row exists but
  users.organisation_id matches — handles legacy/inconsistent data

## datetime rules (non-negotiable)

- Always datetime.utcnow() — never datetime.now(timezone.utc)
- Neon stores naive timestamps — timezone-aware datetimes cause
  silent comparison failures in production
- closed_at on fiscal_year_months uses datetime.utcnow()

## close-period endpoint (added 28 Mar 2026)

- Request body: {"period_end": "YYYY-MM-DD"}
- Matches **`fiscal_year_months`** rows using **`_MONTH_END_SQL`** — never **`month_period::date`**
- Manual close updates **`is_closed`** (sign-off). **`is_completed`** remains the automatic completion flag; see **Period close architecture** above.
- A period is closeable if **`is_completed = true`** and the month end date is in the past
- February 2026 closed manually 28 Mar 2026 by aaron@finsightai.tech
- March 2026 becomes closeable after 31 March 2026

## Period scoping architecture (3 Apr 2026)

- is_completed does NOT gate any backend SQL queries. All report endpoints accept period_start and period_end parameters. The frontend controls period scoping via FY context, not the backend.
- _resolve_default_period_end() is a fallback only — frontend always sends explicit period_start/period_end when an FY is selected. The fallback exists for backwards compatibility and direct API calls without FY context.

## WS4.5 backlog — auto-close overdue periods

- Auto-close any is_completed=true, is_closed=false months where end date
  is more than 5 days in the past, on every fy-context load
- Currently auto-close backlog only runs when last_closed is None
- Required so new users connect and see all past periods already closed
  without needing manual intervention

## Agent module — WS6 (live 11–16 Apr 2026)

### New tables
- agent_requests — id, organisation_id, user_id, agent_type, input_params, status, created_at, completed_at
- agent_responses — id, request_id, response_json, confidence, tokens_used, latency_ms, created_at

### New files
- app/routers/agents/variance_investigator.py — POST /api/v1/agents/variance-investigator/investigate. Rate limited 5/min. Auth required.
- app/services/agent_service.py — full orchestration: pending → Xero fetch → Claude API → response → complete/failed. Model: claude-sonnet-4-6. Prompt caching enabled (cache_control: ephemeral on system block).
- app/services/xero_queries.py — get_transactions_for_account(), get_budget_for_account(). Pure httpx.
- app/services/xero_service.py — shared credential layer. get_valid_xero_credentials().

### driver_type canonical enum
`new_supplier | volume_change | timing | misclassification | other`
price_change was removed in commit 1784ac3 (ADR-010). Do NOT re-introduce it anywhere.

### Agent session commit trail
- 015bb74: router stub (501)
- 980bc86: xero_service.py
- db9e52c: xero_queries.py
- 1b688e8: agent_service.py orchestration
- 5b71a5c + 1bf503e: router wired, rate limited, deployed
- 1784ac3: prompt engineering — model pin, few-shot, driver_type definitions, prompt caching
- a02a32a: removed price_change from driver_type Literal (ADR-010)

## Session commit trail — 28 Mar 2026

563adbd — fix: YYYY-MM date format crash in fy-context
2217239 — fix: strict month_period parsing, no blind to_date
b57eaf5 — fix: GET /organisations/me 500 — add /me route before /{org_id}
8624c95 — fix: GET /settings 405 — add GET handler
cb7bc8c — fix: allow org access via users.organisation_id fallback
06ca117 — fix: GET /organisations/me 404 — multi-path org resolution
e2133fc — fix: POST /close-period 500 — YYYY-MM breaks ::date cast

## Session commit trail — 30 Mar 2026

4ac35f0 — feat: add completed-periods endpoint, update close-period to use fiscal_year_months, fix generate_fy_rows refresh
686ecc5 — fix: read month_number instead of month_index in completed-periods endpoint
5ab70b5 — feat: extend initial Xero sync from 12 to 24 months for prior year comparison

## Session commit trail — 3 Apr 2026

eb2c877 — merge: staging into main — FY rollover backend fixes (verified on staging)
f1bb211 — merge: feat/fy-selector into staging — FY rollover backend fixes
157045d — feat: GET /reports/available-fys endpoint for FY selector

## Session commit trail — 5 Apr 2026

883d069 — feat: POST /admin/orgs/{org_id}/sync for admin-level resyncs
501411c — feat: set active_org_id on registration, eager-load active_organisation
0d09e39 — feat: extend Xero OAuth callback to support multi-org connect
57d72ef — feat: GET /auth/my-orgs and POST /auth/switch-org endpoints
6702c4e — feat: resolve active org from active_org_id across all endpoints

## Session commit trail — 11–14 Apr 2026

9042101 — fix: commentary hardcodes fy_start_month=4 — dynamic FY context
0c972ec — refactor: extract _get_fy_start_month() — 13 call sites
0ffd7e1 — feat(analytics): PostHog cleanup — sandbox filter structural, pnl_module_viewed
ffb416f — feat(marketing): useScrollDepthSections — per-section PostHog events
980bc86 — feat(agents): xero_service.py shared credential layer
db9e52c — feat(agents): xero_queries.py Xero data fetching library
1b688e8 — feat(agents): agent_service.py full orchestration layer
5b71a5c + 1bf503e — feat(agents): variance_investigator router wired, rate limited, deployed
1784ac3 — feat(agents): prompt engineering — model pin claude-sonnet-4-6, few-shot, caching
a02a32a — fix(agents): remove price_change from driver_type Literal (ADR-010)

## Session commit trail — 16 Apr 2026

81ea950 — feat(security): MultiFernet rotation for XERO_TOKEN_ENCRYPTION_KEY (F3b step 1 of 2)
a3514f2 — feat(security): revert to single Fernet after v2 re-encryption complete (F3b step 2 of 2)

## Budget boundary detection (5 Apr 2026)

- **budget_monthly.source** column added (VARCHAR 20, nullable). Values: `xero_sync`, `csv_upload`, `auto_prior_year`, NULL (legacy rows).
- **budget_service.py** (`app/services/budget_service.py`): shared helpers `get_budget_status()` and `get_budget_source()`. Used by reports.py and commentary.py.
- **Budget status detection**: all 5 AvB endpoints (`/reports/avb`, `/reports/avb-kpis`, `/reports/avb-bridge`, `/reports/avb-summary`, `/reports/trend`) now return `budget_status` (`no_budget` | `partial_budget` | `full_budget`) and `budget_source` (`xero_sync` | `csv_upload` | `auto_prior_year` | null).
- **Commentary skip**: `POST /commentary/generate` skips the Anthropic API call and returns `{"skip": true, "reason": "no_budget", ...}` when `module = "actual_vs_budget"` and no budget exists for the current FY. Other modules (executive_summary, revenue_summary, scenario_planning) are unaffected.
- **POST /budgets/generate-from-actuals**: auto-generates current FY budget from prior year actuals. Reads `financial_line_items` for FY(N-1), shifts periods +1 year, writes to `budget_monthly` with `source = 'auto_prior_year'`. Returns 409 if budget already exists, 404 if no prior year actuals.
- **Migration**: `app/db/migrations/add_source_to_budget_monthly.sql` — run on staging first, then production.
- **Two budget tables exist**: `budget_monthly` (used by all AvB queries, Xero sync, CSV upload) and `budgets` (orphan CRUD table, not used by reporting). See P3 item 3M in session-handoff.md.

## Session commit trail — 5 Apr 2026 (budget boundary detection)

96d8a5e — feat(schema): add source column to budget_monthly
174421a — feat(budget): add budget_service with get_budget_status helper
6b1a019 — feat(reports): add budget_status and budget_source to all AvB endpoints
a6fbfbd — feat(commentary): skip AI call when no budget exists for AvB module
909c80b — feat(budgets): POST /budgets/generate-from-actuals endpoint
b75ad37 — feat(budget): set source column on Xero sync and CSV upload writes

## Known issues (30 Mar 2026)

- **Duplicate org names in production:** two organisations both named "FinSight AI": **`2a291c1b-926e-4e2f-9dfa-5fc717960b4c`** (sandbox, **aaron@finsightai.tech**) and **`109ff319`** (**aaronmelvin123@gmail.com**). **`fiscal_year_months`** is only populated for the sandbox org. Multi-org cleanup needed.
- **`next_to_complete`:** **`null`** on staging (no incomplete months in staging data) vs **`"2026-03"`** on production — data difference, not a bug.

## Obsidian Vault — Context Layer

The vault at `../FinSight-AI-Vault/` is the context layer for all Claude Code sessions. Read the relevant files before starting work.

### Session start checklist

1. Read `../FinSight-AI-Vault/02-Sessions/session-handoff.md` — live status, current sprint, blockers
2. Read `../FinSight-AI-Vault/00-Context/project-master.md` — permanent project facts
3. `git pull origin main`
4. Check current branch

### Files relevant to backend work

| File | Read when |
|---|---|
| `00-Context/neon-schema.md` | Any database work — tables, columns, migrations |
| `00-Context/api-endpoints.md` | Adding or modifying endpoints |
| `00-Context/infrastructure.md` | Deployment, Cloud Run, GCP config |
| `00-Context/architecture-decisions.md` | Checking why a decision was made |
| `01-Team/software-engineer.md` | Backend build sessions — forensic debugging protocol, deployment rules, technical constants |
| `01-Team/chief-technology-officer.md` | Architecture decisions, code review, security |
| `04-Specs/ws6-agent-module.md` | Agent module build — schema, API contract, file structure |
| `04-Specs/ws4.5-beta-stabilisation.md` | Bug fixes, stabilisation priorities |
| `03-Reviews/codebase-review-april-2026.md` | Security findings, code quality issues |

### Sync discipline

At the end of every build session where a permanently true fact changed:

1. Check `../FinSight-AI-Vault/00-Context/sync-rules.md` for which files need updating
2. Update the relevant vault files (neon-schema.md if new table, api-endpoints.md if new endpoint, etc.)
3. If vault structure changed (new files), update this CLAUDE.md

**Trigger prompt**: "Read ../FinSight-AI-Vault/00-Context/sync-rules.md. Based on the work completed in this session, identify which vault files need updating and update them now."

### Forensic debugging protocol

All code changes follow three mandatory phases before any push:

1. **Pre-change**: Read actual code from disk (sed -n / grep) before modifying. Confirm root cause through evidence.
2. **Post-change**: Re-read modified files from disk. Run manual verification against affected endpoint. Reconcile financial calculations against baseline (Revenue £41,696, COGS £1,950, OpEx £18,429, EBITDA £21,317). One commit per concern.
3. **Pre-push**: Confirm branch, run build validation, verify staging end-to-end, check git diff. No hardcoded IDs or secrets.

Output a self-review checklist at the end of every code task.

### Handoff protocol

When completing an API endpoint that the frontend will consume, provide:
- Endpoint URL and method
- Complete request schema (field names, types, required/optional)
- Complete response schema (field names, types, nested structures)
- Error response format (status codes, error body)
- Example curl command from staging

---

## Pre-commit checklist (mandatory — April 2026)

### Security
- [ ] No hardcoded secrets, tokens, or API keys
- [ ] All SQL uses text() with parameterised values — no f-strings
- [ ] All new endpoints have Depends(get_current_user) unless explicitly public

### asyncpg type safety
- [ ] VARCHAR → Python str (NEVER datetime.date)
- [ ] BOOLEAN → Python bool
- [ ] UUID → Python str
- [ ] TIMESTAMPTZ → datetime with tzinfo or ISO str
- [ ] All NOT NULL columns provided in every INSERT

### Deployment
- [ ] Deploy from ~/finsight-backend (not ~/) — Dockerfile not Buildpacks
- [ ] Deploy to staging first, verify, then production
- [ ] git diff reviewed verbatim before commit
- [ ] Before `gcloud run services describe --format=json`: pipe through `jq 'del(.. | .value?)'` to avoid printing plaintext secrets to transcript
- [ ] To remove secret-mounted env vars use `--remove-secrets`, NOT `--remove-env-vars`

### Schema
- [ ] Schema change? Write migration SQL + backfill for existing orgs
- [ ] Update neon-schema.md in Obsidian vault

### Git
- [ ] Commit format: fix(scope): / feat(scope): / chore(scope):
- [ ] No print() or logger.debug() with tokens, emails, or org IDs

## Critical active risks (April 2026)

- **Secret Manager v1 destroy pending:** v1 disabled 16 Apr 2026. Destroy after 23–30 Apr soak: `gcloud secrets versions destroy 1 --secret=xero-token-encryption-key --project gen-lang-client-0798522650`
- **Shared Cloud Run service accounts:** prod + staging both use `520129376224-compute@developer.gserviceaccount.com`. Least-privilege violation — fix before first paying customer.
- API keys: rotate any exposed or hardcoded keys immediately
- SECRET_KEY: audit and replace weak or hardcoded values
- Full findings: ~/Documents/FinSight GitHub repo/FinSight-AI-Vault/03-Reviews/codebase-review-april-2026.md
