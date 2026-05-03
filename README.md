# SRE-AI

SRE-AI is a Docker-first, multi-agent incident platform:

- `history-agent`: receives and deduplicates incoming alerts, stores incidents/events, and provides history APIs
- `report-agent`: generates incident reports from supervisor context
- `supervisor-agent`: owns incident lifecycle transitions and AI analysis
- `postgres`: durable storage
- `nginx`: reverse proxy, API facade, and React UI host
- `prometheus`, `alertmanager`, `node-exporter`, and `grafana` for observability
- `jaeger`: optional distributed tracing

Everything is wired for local/VM deployment with one compose file.

---

## Repository map

- `services/history-agent/` service implementation, tests entrypoints, and local README
- `services/report-agent/` service implementation and local README
- `services/supervisor-agent/` service implementation and local README
- `services/nginx/` reverse-proxy and Vite React UI
- `shared/` shared models, database helpers, schemas, and clients
- `infra/postgres/` DB bootstrap + migrations
- `tests/` high-signal API/shared-unit tests
- `config/llm_config.json` runtime LLM routing config (mounted into containers)

---

## Quick start

### 1) Prerequisites

- Docker Engine + Docker Compose v2
- `git` (for deployments)
- Optional for local UI development: Node 20 (the Docker build handles this automatically)

### 2) Configure environment

Create `.env` in repository root from the template:

```bash
cp .env.example .env
```

Then override these values for your environment (minimum required for local run):

```bash
POSTGRES_DB=sre_ai
POSTGRES_USER=sre_ai
POSTGRES_PASSWORD=change_me
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://sre_ai:change_me@postgres:5432/sre_ai

DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_RECYCLE_SECONDS=1800

HISTORY_AGENT_PORT=8001
REPORT_AGENT_PORT=8002
SUPERVISOR_AGENT_PORT=8003
NGINX_PORT=8080
PROMETHEUS_PORT=9090
ALERTMANAGER_PORT=9093
NODE_EXPORTER_PORT=9100
GRAFANA_PORT=3000
JAEGER_UI_PORT=16686
JAEGER_AGENT_PORT=6831
```

Keep the remaining values from `.env.example` unless you have a different deployment target.

Set strong credentials for passwords and API keys before production deployment.

### 3) Start the stack

```bash
docker compose up -d --build
```

### 4) Verify all services are healthy

```bash
docker compose ps
docker compose logs -f --tail=100 nginx
```

You can also probe health endpoints directly:

```bash
curl -s http://127.0.0.1:8080/api/history/health
curl -s http://127.0.0.1:8080/api/report/health
curl -s http://127.0.0.1:8080/api/supervisor/health
```

---

## Accessing the UI

Default public entrypoint is `http://<server-ip>:8080` because `NGINX_PORT` defaults to `8080`.

- If you open `:80` and see nothing, Nginx is usually not bound to that host port because `NGINX_PORT` defaults to `8080`.
- To use port 80, set `NGINX_PORT=80` in `.env`, then run:

```bash
docker compose up -d --build nginx
```

- To verify host binding:

```bash
docker compose port nginx 80
```

- Use the SPA directly:

  - `/` — Dashboard
  - `/incidents` — Incident queue with filtering
  - `/incidents/:incidentId` — Incident details and timeline
  - `/workflow` — End-to-end workflow simulator
  - `/agents` — Service readiness/status
  - `/settings` — LLM routing and runtime API keys

---

## Request flow

All browser and webhook traffic enters through `nginx` on `NGINX_PORT` (`8080` by default). Nginx serves the React UI and forwards `/api/*` requests to the correct agent.

```text
Browser / Alertmanager
        |
        v
nginx :8080
        |
        +--> React UI routes: /, /incidents, /workflow, /integrations, /settings
        |
        +--> /api/history/* and /api/alertmanager/webhook
        |       |
        |       v
        |   history-agent :8001
        |       - validates incoming webhooks
        |       - deduplicates alerts by fingerprint/grouping key
        |       - opens or reuses incidents
        |       - appends immutable history events
        |       - queues supervisor.analyze jobs
        |
        +--> /api/supervisor/*, /api/config/*, /api/test-workflow
        |       |
        |       v
        |   supervisor-agent :8003
        |       - loads incident context from history-agent
        |       - calls the configured LLM with the editable system prompt
        |       - records recommended actions and safe lifecycle transitions
        |       - calls report-agent after queued analysis
        |
        +--> /api/report/*
                |
                v
            report-agent :8002
                - loads incident context from history-agent
                - calls the configured LLM with the editable report prompt
                - stores report.report_generated events
                - optionally sends reports to Mattermost
```

Automatic Alertmanager path:

```text
Alertmanager firing alert
  -> POST /api/alertmanager/webhook
  -> history-agent stores alert + incident events
  -> event queue creates supervisor.analyze
  -> supervisor-agent analyzes the incident
  -> report-agent generates the report
  -> Mattermost delivery runs if enabled
```

Manual operator path:

```text
Operator opens UI
  -> nginx serves React app
  -> UI calls /api/history/dashboard and incident APIs
  -> operator can run /workflow, change LLM routes/prompts in /settings,
     connect Alertmanager/Mattermost in /integrations, or trigger reports manually.
```

Data persistence path:

```text
agents -> postgres
  - alerts table stores raw normalized alert payloads
  - incidents table stores current projection/state
  - incident_events stores append-only event history
  - event_queue stores async supervisor work
  - dead_letter_queue stores failed retryable operations
```

---

## Service endpoints

### Exposed by compose (host ports)

| Service | Port | Endpoint |
| --- | --- | --- |
| history-agent | `8001` | `GET /health`, `GET /ready`, plus incident APIs |
| report-agent | `8002` | `GET /health`, `GET /ready`, report generation/retrieval APIs |
| supervisor-agent | `8003` | `GET /health`, `GET /ready`, lifecycle & config APIs |
| nginx UI/API | `8080` (or `NGINX_PORT`) | Browser UI + API facade |
| prometheus | `9090` (or `PROMETHEUS_PORT`) | scrape UI and metrics rules UI |
| alertmanager | `9093` (or `ALERTMANAGER_PORT`) | alerting UI and silence/group view |
| grafana | `3000` (or `GRAFANA_PORT`) | dashboard UI (Prometheus pre-provisioned) |
| node-exporter | `9100` (or `NODE_EXPORTER_PORT`) | host/node metrics scraper |
| jaeger UI | `16686` | traces |

### Nginx API facade

All frontend/API traffic is served through one listener, prefixed by `/api`:

- History (prefix `/api/history/` and `/api/`)
  - `GET /api/history/health`
  - `GET /api/history/ready`
  - `POST /api/history/alerts`
  - `POST /api/alertmanager/webhook` (Alertmanager-compatible webhook forwarded to alert ingestion)
  - `GET /api/history/incidents`
  - `GET /api/history/incidents/{incident_id}`
  - `GET /api/history/incidents/{incident_id}/events/replay`
  - `GET /api/history/dashboard`
  - `GET /api/history/alerts/recent`
- Report (prefix `/api/report/`)
  - `GET /api/report/health`
  - `GET /api/report/ready`
  - `GET /api/report/integrations/mattermost`
  - `PUT /api/report/integrations/mattermost`
  - `POST /api/report/integrations/mattermost/test`
  - `POST /api/report/{incident_id}`
  - `GET /api/report/{incident_id}`
- Supervisor config + workflow (prefix `/api/supervisor/` for status/ops, `/api/config/` and `/api/test-workflow` for settings)
  - `GET /api/supervisor/health`
  - `GET /api/supervisor/ready`
  - `POST /api/supervisor/analyze`
  - `POST /api/supervisor/queue/analyze`
  - `POST /api/supervisor/investigate|mitigate|resolve|close|acknowledge`
  - `GET /api/supervisor/settings`
  - `PUT /api/supervisor/settings`
  - `GET /api/supervisor/dlq`
  - `GET /api/supervisor/queue`
  - `GET /api/config/llm`
  - `POST /api/config/llm`
  - `GET /api/config/llm/secrets`
  - `POST /api/config/llm/secrets`
  - `POST /api/config/llm/test/{agent}`
  - `POST /api/test-workflow`

---

## Alert API usage examples

Submit a single alert:

```bash
curl -X POST http://127.0.0.1:8080/api/history/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "source": "pagerduty",
    "severity": "critical",
    "summary": "Checkout latency above SLO",
    "labels": {"service": "checkout", "namespace": "payments"},
    "payload": {"description": "p95 latency > 2s"}
  }'
```

Submit a batch:

```bash
curl -X POST http://127.0.0.1:8080/api/history/alerts \
  -H "Content-Type: application/json" \
  -H 'Idempotency-Key: batch-01' \
  -d '{
    "alerts": [
      {"source": "prometheus", "summary": "HTTP 5xx surge", "payload": {"value": 1}},
      {"source": "prometheus", "summary": "Disk usage", "payload": {"value": 2}}
    ]
  }'
```

Run the full workflow from UI payload (simulated):

```bash
curl -X POST http://127.0.0.1:8080/api/test-workflow \
  -H "Content-Type: application/json" \
  -d '{
    "source": "ui-test",
    "summary": "Checkout latency is above SLO",
    "payload": {"description": "p95 latency above 2s for 10 minutes"}
  }'
```

Connect Alertmanager by IP and port:

1. Open `http://<server-ip>:8080/integrations`.
2. Enter the public IP/DNS and port that Alertmanager can reach.
3. Copy the generated webhook URL, usually:

```text
http://<server-ip>:8080/api/alertmanager/webhook
```

4. Add it to Alertmanager:

```yaml
receivers:
  - name: sre-ai
    webhook_configs:
      - url: http://<server-ip>:8080/api/alertmanager/webhook
        send_resolved: false
```

Every firing Alertmanager alert is ingested by `history-agent`. The ingestion path queues `supervisor-agent`, and the supervisor queue worker generates a report after analysis, so the full History -> Supervisor -> Report workflow runs automatically.

Connect Mattermost report delivery:

1. Open `http://<server-ip>:8080/integrations`.
2. Paste a Mattermost incoming webhook URL in the Mattermost delivery card.
3. Enable delivery, optionally set a channel override and bot username, then save.
4. Use **Send Mattermost Test** to verify the webhook.

When enabled, every newly generated report is posted by `report-agent` to Mattermost. Report storage does not depend on Mattermost availability; delivery failures are written to the dead-letter queue as `report.deliver_mattermost`.

---

## LLM configuration and dynamic routing

`config/llm_config.json` is mounted to services via `LLM_CONFIG_PATH` and read by runtime.

You can:

- update routing through UI (`/settings`) with `POST /api/config/llm`
- test provider-route per agent using `POST /api/config/llm/test/{agent}`
- persist API keys in ignored runtime secrets using `POST /api/config/llm/secrets`
- check provider readiness with `GET /api/config/llm/secrets`

Example config shape is:

```json
{
  "providers": ["openrouter", "llmgateway", "gapgpt"],
  "models": {
    "openrouter": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5", "google/gemini-2.5-pro"],
    "llmgateway": ["zai/glm-5.1"],
    "gapgpt": ["gapgpt-qwen-3.5", "gapgpt-qwen-3.6", "gpt-5.2", "gemini-3-pro-preview"]
  },
  "provider_settings": {
    "openrouter": {
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "default_model": "openai/gpt-4o-mini",
      "proxy_url": "http://185.255.89.232:5070"
    }
  },
  "agents": {
    "supervisor": {"provider": "llmgateway", "model": "zai/glm-5.1"},
    "report": {"provider": "openrouter", "model": "meta-llama/llama-3.1-8b-instruct"}
  },
  "prompts": {
    "supervisor": "You are an SRE supervisor...",
    "report": "Create a concise SRE incident report in markdown..."
  }
}
```

The `/settings` UI can edit provider/model routes, each LLM-backed agent system prompt, provider base URLs, and per-provider proxy URLs. Prompt and proxy changes are saved to `config/llm_config.json` and take effect on the next LLM call without rebuilding containers.

OpenRouter is configured to use `http://185.255.89.232:5070` by default. To change it in the UI, open `/settings`, edit **Provider networking -> OpenRouter -> HTTP/SOCKS proxy URL**, then save provider settings. Leave the proxy field blank to send provider traffic directly. Environment variables such as `OPENROUTER_PROXY_URL` or `LLM_PROXY_URL` override the file-backed UI setting.

The committed GapGPT model list is populated from `GET https://api.gapgpt.app/v1/models` so the `/settings` model dropdown includes all currently advertised GapGPT model IDs, including chat, image, audio, embedding, and TTS models. Some non-chat models may not work for supervisor/report chat-completion calls.

The committed OpenRouter model list is populated from `GET https://openrouter.ai/api/v1/models` so the `/settings` model dropdown includes all currently advertised OpenRouter model IDs. OpenRouter publishes some free, preview, image, and non-chat variants; use chat-completion capable models for supervisor/report routes.

There is no history model setting by design. `history-agent` is deterministic and does not call an LLM; it verifies webhooks, deduplicates alerts, persists the append-only timeline, and serves incident context. Only `supervisor-agent` and `report-agent` use model routing.

---

## Environment reference (short list)

- Database
  - `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
  - `POSTGRES_HOST`, `POSTGRES_PORT`, `DATABASE_URL` (overrides host/db variables)
  - pool: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS`
- Service ports
  - `HISTORY_AGENT_PORT`, `REPORT_AGENT_PORT`, `SUPERVISOR_AGENT_PORT`
  - `NGINX_PORT`, `PROMETHEUS_PORT`, `ALERTMANAGER_PORT`, `NODE_EXPORTER_PORT`, `GRAFANA_PORT`, `JAEGER_UI_PORT`, `JAEGER_AGENT_PORT`
- URLs
  - `HISTORY_AGENT_URL`, `REPORT_AGENT_URL`, `SUPERVISOR_AGENT_URL`
  - `VITE_API_BASE_URL` (defaults to `/api`)
- Security and ingestion behavior
  - `ALERT_WEBHOOK_SECRET` (optional webhook signature enforcement)
  - `MAX_ALERT_JSON_BYTES`, `MAX_ALERT_BATCH_SIZE`
  - `DEFAULT_SLA_HOURS`, `REOPEN_STALE_AFTER_HOURS`
- LLM and HTTP
  - `AI_PROVIDER`, `AI_MODEL`, provider keys/base URLs
  - `OPENROUTER_PROXY_URL`, `LLM_GATEWAY_PROXY_URL`, `GAPGPT_PROXY_URL`, `LLM_PROXY_URL`
  - `HTTP_TIMEOUT`, `HTTP_MAX_RETRIES`, `HTTP_BACKOFF_SECONDS`
  - `HTTP_CIRCUIT_BREAKER_THRESHOLD`, `HTTP_CIRCUIT_BREAKER_RESET_SECONDS`
  - `LLM_CONFIG_PATH`, `LLM_RUNTIME_SECRETS_PATH`
  - `REPORT_INTEGRATIONS_CONFIG_PATH`, `MATTERMOST_WEBHOOK_URL`
- Grafana admin
  - `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`

For any non-dev environment, prefer a secret manager over checked-in `.env` values.

---

## Security notes

- If `ALERT_WEBHOOK_SECRET` is set, alert ingestion expects:
  - `X-SRE-AI-Signature: sha256=<hmac>` or
  - `X-Hub-Signature-256: sha256=<hmac>`
- Runtime keys and runtime secrets are never committed by design (`.gitignore` includes `config/llm_runtime_secrets.json` and `config/report_integrations.json`).
- Request correlation IDs are carried through internal calls for traceability.
- DB constraints and idempotency keys protect against duplicate event ingestion and duplicate status transitions.

---

## Operations and troubleshooting

- Why the UI loads at `:80` not `:8080`:
  - Set `NGINX_PORT=80`, restart nginx service, and confirm host firewall allows inbound `80`.
  - If host still blocks it, expose an internet-facing port on your load balancer or security group.
- If ports look fine but API/UI still blank:
  - `docker compose logs -f nginx`
  - `docker compose exec nginx nginx -T | sed -n '1,240p'` (or inspect `services/nginx/nginx.conf`)
- If the browser shows `504 Gateway Time-out` on `/workflow`, report generation, or AI actions:
  - `docker compose logs nginx | grep -Ei '504|timed out|upstream'`
  - check the agent logs for slow LLM calls or provider retries
  - verify API keys/provider routing in `/settings`
  - long-running AI routes use extended nginx proxy timeouts, but an unreachable LLM provider can still delay fallback output
- If services fail to become healthy:
  - check DB readiness first (`docker compose logs -f postgres`)
  - verify migrations exist in `infra/postgres/migrations`
  - rebuild and restart with `docker compose up -d --build`
- Full restart and cleanup workflow:
  - `docker compose down`
  - `docker compose up -d --build`
- Data reset for local testing only:
  - remove `postgres_data` volume and redeploy (this drops state).

---

## Testing

Run lightweight checks used by CI:

```bash
python -m compileall shared services
cd services/nginx/ui && npm install && npm run build && cd -
pytest
```

Observability validation:

```bash
docker compose up -d --build
curl -s http://127.0.0.1:${PROMETHEUS_PORT:-9090}/api/v1/rules | jq '.data.groups[].name'
curl -s http://127.0.0.1:${PROMETHEUS_PORT:-9090}/api/v1/alerts | jq '.data.alerts | length'
curl -s http://127.0.0.1:${ALERTMANAGER_PORT:-9093}/api/v2/status
```

You can also force a fireable alert by temporarily stopping `node-exporter`:

```bash
docker compose stop node-exporter
sleep 70
curl -s http://127.0.0.1:${ALERTMANAGER_PORT:-9093}/api/v2/alerts
docker compose start node-exporter
```

---

## CI

- `.github/workflows/ci.yml` runs:
  - Python compile check
  - `docker compose config`
  - UI build check (`npm install && npm run build`)

---

## Notes for local development

- Frontend code lives in `services/nginx/ui/src`.
- API contracts are tested in `tests/test_frontend_assets.py` and route-level checks.
- `docker-compose.bluegreen.yml` includes helper service entries for blue/green experimentation.
- For focused backend debugging, check service logs with `docker compose logs -f <service>`.

---

## References

- `services/history-agent/README.md`
- `services/report-agent/README.md`
- `services/supervisor-agent/README.md`
- `services/nginx/nginx.conf`
- `infra/postgres/init.sql` and `infra/postgres/migrations/*`
- `config/llm_config.json`
