-- Migration: Create budget_monthly table (Workstream 3, Session 4 - Task 2)
-- Required for /reports/budget/upload and AvB: one row per org + account + YYYY-MM period.

CREATE TABLE IF NOT EXISTS budget_monthly (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id   UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    account_code      VARCHAR(50) NOT NULL,
    account_name      VARCHAR(255) NOT NULL,
    reporting_category VARCHAR(100),
    period            CHAR(7) NOT NULL,   -- YYYY-MM
    budget_amount     NUMERIC(15, 2) NOT NULL DEFAULT 0,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at        TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE (organisation_id, account_code, period)
);

CREATE INDEX IF NOT EXISTS idx_budget_monthly_org_period
    ON budget_monthly (organisation_id, period);
CREATE INDEX IF NOT EXISTS idx_budget_monthly_org
    ON budget_monthly (organisation_id);

COMMENT ON TABLE budget_monthly IS 'Monthly budget by account; used for Actual vs Budget (AvB) reporting.';
