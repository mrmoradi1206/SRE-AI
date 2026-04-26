CREATE TABLE IF NOT EXISTS alert_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL DEFAULT 'ingested',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_alert_events_version UNIQUE (alert_id, version)
);

CREATE INDEX IF NOT EXISTS idx_alert_events_alert_id_created_at ON alert_events(alert_id, created_at);
