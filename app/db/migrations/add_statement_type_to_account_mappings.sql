-- Migration: Add statement_type to account_mappings (Workstream 3, Session 4)
-- Run only after confirmation. reporting_category already exists.

ALTER TABLE account_mappings
  ADD COLUMN IF NOT EXISTS statement_type VARCHAR(50);

COMMENT ON COLUMN account_mappings.statement_type IS 'profit_and_loss or balance_sheet';

-- Optional: add check constraint after backfilling (uncomment after updates)
-- ALTER TABLE account_mappings
--   ADD CONSTRAINT chk_statement_type
--   CHECK (statement_type IN ('profit_and_loss', 'balance_sheet'));
