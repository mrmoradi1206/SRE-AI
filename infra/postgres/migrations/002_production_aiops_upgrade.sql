-- Migration 002: Ensure alert_events indexes (table already created in init.sql)
CREATE INDEX IF NOT EXISTS idx_alert_events_alert_id_created_at ON alert_events(alert_id, created_at);
