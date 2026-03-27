# FinSight AI — Backend (finsight-backend)

## What this repo is
FastAPI backend for FinSight AI — a modular SaaS CFO platform. Deployed on Google Cloud Run at api.finsightai.tech.

## Infrastructure
- Runtime: FastAPI on Google Cloud Run (us-central1)
- Latest revision: finsight-backend-00119-v4z
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
