-- The app updates the incident projection before writing the status event in
-- some paths, so the guard must allow already-applied target states.
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

    IF current_status = target_status THEN
        RETURN NEW;
    ELSIF current_status = 'open' AND target_status NOT IN ('investigating') THEN
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
