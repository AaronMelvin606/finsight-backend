-- Period close: track closed fiscal months (applied to Neon production + staging).
ALTER TABLE fiscal_year_months
  ADD COLUMN IF NOT EXISTS is_closed BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS closed_by TEXT;
