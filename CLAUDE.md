# FinSight AI — Backend (finsight-backend)

## What this repo is
FastAPI backend for FinSight AI — a modular SaaS CFO platform. Deployed on Google Cloud Run at api.finsightai.tech.

## Infrastructure
- Runtime: FastAPI on Google Cloud Run (us-central1)
- Production revision: finsight-backend-00146-qjp (deployed 3 Apr 2026)
- Staging revision: finsight-backend-staging-00006-chg (deployed 30 Mar 2026)
- Previous production revision: finsight-backend-00140-gfd (deployed 30 Mar 2026)
- Database: Neon PostgreSQL (9 tables)
- Custom domain: api.finsightai.tech → finsight-backend-520129376224.us-central1.run.app
- Monitoring: Sentry (backend DSN), GCP Monitoring alerts
- Analytics: PostHog (eu.posthog.com)

## Neon tables
users, organisations, xero_connections, account_mappings, budget_monthly, fiscal_years, fiscal_year_months, financial_line_items, registration_allowlist

## Sandbox constants
- Org ID: 2a291c1b-926e-4e2f-9dfa-5fc717960b4c
- Sandbox login: aaron@finsightai.tech / FinSight2026!

## API login (curl / scripts)
- Use **`POST /api/v1/auth/login/json`** with JSON `{"email","password"}` for programmatic login and JWT retrieval.
- **`POST /api/v1/auth/login`** is OAuth2 form (`username` / `password`), not JSON — do not use it for JSON bodies.

## Non-negotiable rules
- All KPI calculations live in the backend. Never move calculations to the frontend.
- Budget ingestion: Path A (Xero GET /budgets) is always preferred. Path B (CSV upload) is the fallback.
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
- Tier 2 complete: GCP Monitoring 401 spike alerts, slowapi rate limiting on /auth/register and /auth/login
- Tier 3 pending (post first customer): audit_log table, failed login lockout
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

### Deployment flow
Normal:  feature branch → staging → verify → merge to main → production
Hotfix:  hotfix branch → main → verify in production → merge back to staging

### Keeping environments in sync after hotfixes
Run in finsight-backend:
  git checkout staging && git merge main && git push origin staging && git checkout main
Run in FinSight-AI---Professional-Growth-Suite:
  git checkout staging && git merge main && git push origin staging && git checkout main

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
- Resolves org in order: (1) fresh DB lookup on users.organisation_id,
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

## Known issues (30 Mar 2026)

- **Duplicate org names in production:** two organisations both named "FinSight AI": **`2a291c1b-926e-4e2f-9dfa-5fc717960b4c`** (sandbox, **aaron@finsightai.tech**) and **`109ff319`** (**aaronmelvin123@gmail.com**). **`fiscal_year_months`** is only populated for the sandbox org. Multi-org cleanup needed.
- **`next_to_complete`:** **`null`** on staging (no incomplete months in staging data) vs **`"2026-03"`** on production — data difference, not a bug.
