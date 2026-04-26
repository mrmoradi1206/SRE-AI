# SRE-AI

SRE-AI is a Docker-first multi-agent incident workflow with three FastAPI services, PostgreSQL, and an nginx-served React SPA.

## Architecture

- `history-agent`: append-only alert ingestion, incident lookup, timeline search, dashboard metrics
- `report-agent`: reads incident context from `history-agent` and writes only `report_generated` events
- `supervisor-agent`: the only service allowed to change `incident.status`; it analyzes, acknowledges, resolves, and closes incidents
- `postgres`: persistence for alerts, incidents, events, and AI settings
- `nginx`: reverse proxy plus static UI hosting on `http://localhost:8080`

## Quick start

```bash
cd "/mnt/d/sre ai/SRE-AI"
cp .env.example .env
# edit .env for real secrets if needed

docker compose up -d --build
```

## Service endpoints

- `http://localhost:8001/health` - history-agent
- `http://localhost:8002/health` - report-agent
- `http://localhost:8003/health` - supervisor-agent
- `http://localhost:8080` - UI through nginx

## Repo layout

- `infra/postgres/` - schema bootstrap and migrations
- `shared/aiops_shared/` - shared DB, schema, HTTP, and utility modules
- `services/history-agent/` - alert ingestion and incident views
- `services/report-agent/` - report generation and report-event storage
- `services/supervisor-agent/` - lifecycle decisions and AI settings
- `services/nginx/` - reverse proxy and React/Vite SPA
