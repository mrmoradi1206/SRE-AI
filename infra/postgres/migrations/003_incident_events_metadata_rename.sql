-- Keep existing deployments aligned with the current SQLAlchemy model.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'incident_events'
          AND column_name = 'metadata'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'incident_events'
          AND column_name = 'event_metadata'
    ) THEN
        ALTER TABLE incident_events RENAME COLUMN metadata TO event_metadata;
    END IF;
END $$;
