CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS incident_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    service TEXT,
    severity TEXT,
    summary TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    resolution TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_knowledge_incident_id ON incident_knowledge(incident_id);
CREATE INDEX IF NOT EXISTS idx_incident_knowledge_service ON incident_knowledge(service);
CREATE INDEX IF NOT EXISTS idx_incident_knowledge_created_at ON incident_knowledge(created_at);
CREATE INDEX IF NOT EXISTS idx_incident_knowledge_embedding ON incident_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 32);

DROP TRIGGER IF EXISTS trg_incident_knowledge_updated_at ON incident_knowledge;
CREATE TRIGGER trg_incident_knowledge_updated_at
BEFORE UPDATE ON incident_knowledge
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
