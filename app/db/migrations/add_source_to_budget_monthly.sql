-- Migration: Add source column to budget_monthly
-- Tracks how each budget row was created: xero_sync, csv_upload, auto_prior_year
-- Nullable — existing rows will have source = NULL (pre-migration legacy data)
-- Run on staging first, then production after verification.

ALTER TABLE budget_monthly
ADD COLUMN IF NOT EXISTS source VARCHAR(20);

COMMENT ON COLUMN budget_monthly.source IS 'Origin of budget row: xero_sync | csv_upload | auto_prior_year | NULL (legacy)';
