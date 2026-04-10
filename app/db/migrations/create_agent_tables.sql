-- Migration: create_agent_tables.sql
-- WS6 Variance Investigator — agent request/response storage
-- Run on staging first, then production. Manual execution only.
-- To add new agent types:
--   ALTER TABLE agent_requests DROP CONSTRAINT agent_requests_agent_type_check,
--   ADD CONSTRAINT agent_requests_agent_type_check
--     CHECK (agent_type IN ('variance_investigator', 'new_agent_type'));

BEGIN;

CREATE TABLE agent_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_type      TEXT NOT NULL
                    CHECK (agent_type IN ('variance_investigator')),
    input_params    JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'complete', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE agent_responses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID NOT NULL REFERENCES agent_requests(id) ON DELETE CASCADE,
    response_json   JSONB NOT NULL,
    confidence      TEXT NOT NULL
                    CHECK (confidence IN ('high', 'medium', 'low')),
    tokens_used     INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_requests_org_created
    ON agent_requests (organisation_id, created_at DESC);

CREATE INDEX idx_agent_requests_status_pending
    ON agent_requests (status)
    WHERE status IN ('pending', 'processing');

CREATE INDEX idx_agent_responses_request
    ON agent_responses (request_id);

COMMIT;
