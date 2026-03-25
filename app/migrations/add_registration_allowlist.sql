CREATE TABLE IF NOT EXISTS registration_allowlist (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    added_by TEXT,
    added_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);

INSERT INTO registration_allowlist (email, added_by, notes)
VALUES
  ('aaron@finsightai.tech', 'system', 'Sandbox account'),
  ('andy@fliwheel.tech', 'system', 'First beta prospect')
ON CONFLICT (email) DO NOTHING;
