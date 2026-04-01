-- Run manually in Neon to revert sandbox after FY rollover testing.
-- Sandbox organisation: 2a291c1b-926e-4e2f-9dfa-5fc717960b4c

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM fiscal_years
        WHERE organisation_id = '2a291c1b-926e-4e2f-9dfa-5fc717960b4c'
          AND fy_year = 2025
          AND is_current = false
    ) THEN
        UPDATE fiscal_years
        SET is_current = true
        WHERE organisation_id = '2a291c1b-926e-4e2f-9dfa-5fc717960b4c'
          AND fy_year = 2025;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fiscal_years
        WHERE organisation_id = '2a291c1b-926e-4e2f-9dfa-5fc717960b4c'
          AND fy_year = 2026
          AND is_current = true
    ) THEN
        UPDATE fiscal_years
        SET is_current = false
        WHERE organisation_id = '2a291c1b-926e-4e2f-9dfa-5fc717960b4c'
          AND fy_year = 2026;
    END IF;
END $$;
