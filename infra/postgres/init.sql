CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'incident_status') THEN
        CREATE TYPE incident_status AS ENUM ('open', 'investigating', 'mitigating', 'resolved', 'closed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'incident_severity') THEN
        CREATE TYPE incident_severity AS ENUM ('critical', 'high', 'medium', 'low', 'unknown');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dead_letter_status') THEN
        CREATE TYPE dead_letter_status AS ENUM ('pending', 'retrying', 'processed', 'failed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'queue_status') THEN
        CREATE TYPE queue_status AS ENUM ('pending', 'processing', 'retrying', 'completed', 'failed');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint TEXT NOT NULL,
    grouping_key TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    summary TEXT,
    severity incident_severity NOT NULL DEFAULT 'unknown',
    status incident_status NOT NULL DEFAULT 'open',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    resolved_by TEXT,
    escalated_to TEXT,
    mitigated_at TIMESTAMPTZ,
    mitigated_by TEXT,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    closed_by TEXT,
    sla_deadline TIMESTAMPTZ,
    sla_violated BOOLEAN NOT NULL DEFAULT FALSE,
    mttr_seconds INTEGER,
    source_count INTEGER NOT NULL DEFAULT 1,
    projection_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    grouping_key TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    event_key TEXT NOT NULL UNIQUE,
    source TEXT,
    severity TEXT NOT NULL DEFAULT 'unknown',
    correlation_id UUID,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL DEFAULT 'ingested',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_alert_events_version UNIQUE (alert_id, version)
);

CREATE TABLE IF NOT EXISTS incident_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_version INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    causation_id UUID,
    correlation_id UUID,
    idempotency_key TEXT UNIQUE,
    event_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sequence_number BIGINT NOT NULL,
    CONSTRAINT uq_incident_events_sequence UNIQUE (stream_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS ai_settings (
    id SERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key TEXT,
    extra_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id SERIAL PRIMARY KEY,
    queue_key TEXT NOT NULL UNIQUE,
    service TEXT NOT NULL,
    operation TEXT NOT NULL,
    status dead_letter_status NOT NULL DEFAULT 'pending',
    correlation_id UUID,
    idempotency_key TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS event_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic TEXT NOT NULL,
    stream_id UUID,
    correlation_id UUID,
    idempotency_key TEXT UNIQUE,
    status queue_status NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    not_before TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alerts_grouping_key ON alerts(grouping_key);
CREATE INDEX IF NOT EXISTS idx_alerts_dedup_key ON alerts(dedup_key);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_incident_id ON alerts(incident_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_alert_id_created_at ON alert_events(alert_id, created_at);
CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint ON incidents(fingerprint);
CREATE INDEX IF NOT EXISTS idx_incidents_grouping_key ON incidents(grouping_key);
CREATE INDEX IF NOT EXISTS idx_incidents_dedup_key ON incidents(dedup_key);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_last_seen_at ON incidents(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_incident_events_stream_id ON incident_events(stream_id);
CREATE INDEX IF NOT EXISTS idx_incident_events_correlation_id ON incident_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_incident_events_created_at ON incident_events(created_at);
CREATE INDEX IF NOT EXISTS idx_dlq_status_next_retry ON dead_letter_queue(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_event_queue_topic_status_not_before ON event_queue(topic, status, not_before);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_incidents_updated_at ON incidents;
CREATE TRIGGER trg_incidents_updated_at
BEFORE UPDATE ON incidents
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_ai_settings_updated_at ON ai_settings;
CREATE TRIGGER trg_ai_settings_updated_at
BEFORE UPDATE ON ai_settings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_dlq_updated_at ON dead_letter_queue;
CREATE TRIGGER trg_dlq_updated_at
BEFORE UPDATE ON dead_letter_queue
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_event_queue_updated_at ON event_queue;
CREATE TRIGGER trg_event_queue_updated_at
BEFORE UPDATE ON event_queue
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_incident_event_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'incident_events are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_incident_events_no_update ON incident_events;
CREATE TRIGGER trg_incident_events_no_update
BEFORE UPDATE ON incident_events
FOR EACH ROW
EXECUTE FUNCTION enforce_incident_event_immutable();

DROP TRIGGER IF EXISTS trg_incident_events_no_delete ON incident_events;
CREATE TRIGGER trg_incident_events_no_delete
BEFORE DELETE ON incident_events
FOR EACH ROW
EXECUTE FUNCTION enforce_incident_event_immutable();

CREATE OR REPLACE FUNCTION validate_incident_status_transition()
RETURNS TRIGGER AS $$
DECLARE
    current_status incident_status;
    target_status incident_status;
BEGIN
    IF NEW.event_type <> 'supervisor.status_changed' THEN
        RETURN NEW;
    END IF;

    current_status := (SELECT status FROM incidents WHERE id = NEW.stream_id);
    target_status := COALESCE((NEW.payload->>'to')::incident_status, current_status);

    IF current_status = 'open' AND target_status NOT IN ('investigating') THEN
        RAISE EXCEPTION 'invalid transition from % to %', current_status, target_status;
    ELSIF current_status = 'investigating' AND target_status NOT IN ('mitigating') THEN
        RAISE EXCEPTION 'invalid transition from % to %', current_status, target_status;
    ELSIF current_status = 'mitigating' AND target_status NOT IN ('resolved') THEN
        RAISE EXCEPTION 'invalid transition from % to %', current_status, target_status;
    ELSIF current_status = 'resolved' AND target_status NOT IN ('closed') THEN
        RAISE EXCEPTION 'invalid transition from % to %', current_status, target_status;
    ELSIF current_status = 'closed' AND target_status <> 'closed' THEN
        RAISE EXCEPTION 'invalid transition from % to %', current_status, target_status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_incident_status_transition ON incident_events;
CREATE TRIGGER trg_validate_incident_status_transition
BEFORE INSERT ON incident_events
FOR EACH ROW
EXECUTE FUNCTION validate_incident_status_transition();
