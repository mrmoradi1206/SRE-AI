# AIOps Platform

A Docker-first multi-agent incident investigation platform composed of three FastAPI services:

- `history-agent`: ingests Alertmanager webhooks, deduplicates alerts, and stores incident history.
- `supervisor-agent`: fetches context, analyzes incidents with OpenRouter, and persists structured analysis.
- `report-agent`: renders incident reports and delivers them to Mattermost or Teams.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

## Services

- `http://localhost:8001/health`
- `http://localhost:8002/health`
- `http://localhost:8003/health`
- `http://localhost:8080`

## Notes

- All components run in Docker; no local Python environment is required.
- PostgreSQL schema is initialized from `infra/postgres/init.sql`.
- If OpenRouter is unavailable, the supervisor falls back to a rule-based analysis with `confidence: 0.0`.
