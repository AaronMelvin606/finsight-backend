-- ============================================================================
-- Multi-org migration — STAGING ONLY
-- Run on staging Neon via Cursor Agent chat. Do NOT run on production.
-- Date: 5 April 2026
-- ============================================================================

-- STEP 1: Add active_org_id column to users
ALTER TABLE users
ADD COLUMN IF NOT EXISTS active_org_id UUID REFERENCES organisations(id) ON DELETE SET NULL;

-- STEP 1b: Add unique constraint on organisation_members (if not already present)
ALTER TABLE organisation_members
ADD CONSTRAINT uq_org_member_org_user UNIQUE (organisation_id, user_id);

-- STEP 2: Backfill organisation_members for all existing users
-- (ensures every user with an org has an ownership row in the junction table)
INSERT INTO organisation_members (id, organisation_id, user_id, role, joined_at)
SELECT gen_random_uuid(), organisation_id, id, 'owner', now()
FROM users
WHERE organisation_id IS NOT NULL
ON CONFLICT (organisation_id, user_id) DO NOTHING;

-- STEP 3: Set active_org_id from existing organisation_id
UPDATE users
SET active_org_id = organisation_id
WHERE organisation_id IS NOT NULL
  AND active_org_id IS NULL;

-- STEP 4: Verification — expect 0 rows
SELECT id, email, organisation_id, active_org_id
FROM users
WHERE organisation_id IS NOT NULL
  AND active_org_id IS NULL;
