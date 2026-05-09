# Cortex

Cortex is a Docker-first, supervisor-led multi-agent incident platform:

- `history-agent`: receives and deduplicates incoming alerts, stores incidents/events, and provides history APIs
- `report-agent`: generates incident reports from supervisor context
- `supervisor-agent`: owns incident lifecycle transitions and ReAct-style AI analysis
- `observability-agent`: LLM-backed Prometheus/Elasticsearch analysis agent for supervisor tool calls and UI drilldowns
- `repo-agent`: LLM-backed GitLab commits/MRs analysis agent for incident context
- `redis`: short-lived ReAct memory for supervisor reasoning sessions
- `pgvector`: long-term incident knowledge/RAG memory in Postgres
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
- `services/observability-agent/` FastAPI observability API with Prometheus and Elasticsearch integrations
- `services/repo-agent/` FastAPI GitLab integration API
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
  - `/how-it-works` — Visual Cortex architecture and request-flow map
  - `/incidents` — Incident queue with filtering
  - `/incidents/:incidentId` — Incident details and timeline
  - `/workflow` — End-to-end workflow simulator
  - `/integrations` — Alertmanager, Mattermost, Prometheus, Elasticsearch, and GitLab setup
  - `/agents` — Service readiness/status
  - `/settings` — LLM routing and runtime API keys

---

## Cortex UI guide

The UI is the operator command center. It is designed around one rule: `supervisor-agent` is the Cortex brain, and every specialist agent returns evidence or delivery status back into the incident record.

### Global navigation and header

- **Dashboard** opens the Cortex overview with current incident posture and recent signals.
- **How It Works** opens a visual map of the Cortex brain, agents, memory, integrations, and alert-to-resolution flow.
- **Incidents** opens the triage queue where you search, filter, open, or delete incidents.
- **Test Workflow** opens a safe end-to-end simulator for a synthetic alert.
- **Integrations** opens all external connection settings: Alertmanager, Mattermost, Prometheus, Elasticsearch, and GitLab.
- **Agents** opens live health checks for Docker compose nodes and platform services.
- **Cortex Models** opens LLM routing, prompts, provider networking, proxy, and runtime API key settings.
- **Dark mode / Light mode** switches the browser theme only; it does not change backend behavior.

### Dashboard page

The dashboard is a read-only operations overview.

- **Open incidents**, **Investigating**, **Mitigating**, and **Resolved in 24h** show current counters from `history-agent`.
- **See all** opens the full Incidents queue.
- **Recent incidents** cards open the selected incident detail page.
- **Recent alerts** shows the latest alert samples from the last 24 hours.

### How It Works page

Use this page to explain Cortex to operators, teammates, and stakeholders.

- **Connect integrations** opens the Integrations page so you can wire Alertmanager, Mattermost, Prometheus, Elasticsearch, and GitLab.
- **Run test workflow** opens the simulator so you can send a synthetic alert through the whole Cortex loop.
- **Orbit diagram** shows Supervisor at the center with History, Observability, Repo, and Report agents around it.
- **Alert to resolution** shows the five-step flow from signal ingestion to long-term learning.
- **Cortex parts** explains every major module in the app.
- **How Supervisor thinks** explains the ReAct loop: Thought, Action, Observation, Decision.
- **How SREs use it** explains the operator path: open incident, review logs, run integrations, generate report, approve and learn.
- **SRE operator playbook** explains the real operations workflow in detail: prepare integrations and models, triage incidents, validate agent evidence, mitigate and communicate, resolve, and teach Cortex with approved lessons.
- **Operator principles** reminds SREs to trust but verify LLM hypotheses, preserve real audit evidence, and approve only accurate lessons for long-term memory.

### Incidents page

Use this page to triage and clean incident data.

- **Search summary, fingerprint, grouping key** filters incidents by text.
- **All statuses** filters by lifecycle state: open, investigating, mitigating, resolved, or closed.
- Clicking an incident row opens the full investigation page.
- **Delete** removes that incident, its alert samples, timeline events, and queued actions. Use this mainly for test cleanup.

### Incident detail and investigation page

This is the main SRE workbench for one incident.

- **Ask Cortex Supervisor** runs supervisor analysis for the incident and records supervisor decisions.
- **Investigate** moves the incident into investigating and asks Supervisor to gather more evidence.
- **Mitigate** moves the incident into mitigation and records the operator reason.
- **Resolve** marks the incident resolved from the UI and records the resolution action.
- **Generate Cortex Report** asks `report-agent` to build the current incident report and send it to Mattermost if enabled.
- **Approve & Learn** opens a modal to review/edit root cause and resolution, then saves the approved knowledge into pgvector long-term memory.
- **Delete Incident** removes the current incident and related records.
- **Back** returns to the Incidents queue.
- **Talk to Cortex Supervisor** opens an operator chat lane on the incident page; each question triggers a fresh supervisor investigation pass that asks observability-agent and repo-agent before answering.
- **What each agent did** appears under every chat reply so operators can quickly review supervisor, history, observability, and repo contributions.
- **Cortex command log** shows the supervisor-first flow: Supervisor as commander, Observability and Repo evidence returned to Supervisor, History events, Report actions, and channel delivery records.
- **Supervisor final decision** shows the final structured decision from the latest ReAct trace when available.
- Agent action rows can be expanded to inspect recommended actions, sanitized LLM traces, and raw event details.
- **Chain of Thought Trace** shows the Supervisor ReAct loop as Thought, Action, Observation, and Final decision cards. It polls while the incident is investigating.
- **Similar Past Incidents** shows pgvector/RAG matches that were saved through Approve & Learn.
- **Query Prometheus** runs the PromQL in the input field through `observability-agent`.
- **Search recent errors** asks `observability-agent` to fetch recent Elasticsearch errors and stack traces for the detected service.
- **Fetch GitLab changes** asks `repo-agent` for recent commits and merge requests, optionally using the project ID/path in the field.
- **Raw alert samples** exposes the alert payloads that created or updated the incident.
- **Correlation stub** shows placeholder relationship nodes for future topology/correlation work.
- **Investigation Timeline** is a human-readable incident event stream with filters for all, supervisor, observability, repo, report, history, and system events.
- **Delete event** removes only that timeline entry, not the whole incident.
- **Raw metadata and payload** expands the copyable JSON for a timeline event.
- **Latest report** shows the latest stored report body.
- **All agent actions and channel delivery** shows the report summary, Mattermost delivery status, and copyable markdown summary.

### Test Workflow page

Use this page to verify the full Cortex loop without waiting for a real alert.

- **Reset sample** restores the default synthetic checkout-latency alert JSON.
- **Test Alert** posts the JSON to the workflow API, then runs History -> Supervisor -> Report.
- **Step trace** shows each backend step returned by the workflow.
- **LLM request/response trace (sanitized)** shows model calls without leaking API keys.
- **Supervisor reasoning** shows the structured supervisor response.
- **Final report** shows the generated report response.

### Integrations page

Use this page to connect external systems without rebuilding containers.

- **Alert ingestion mode** lets you choose how Cortex receives Alertmanager alerts:
  - **Push webhook**: Alertmanager posts alerts to Cortex.
  - **Pull API polling**: Cortex polls Alertmanager active alerts every interval.
  - **Both modes**: useful during migration; Cortex deduplicates repeated active alerts.
- **Submit Endpoint Changes** saves the Alertmanager public IP/DNS/port in browser storage and rebuilds the displayed webhook URL, YAML, and curl examples.
- **Endpoint Saved** means the displayed endpoint already matches the saved browser value.
- **Copy saved URL** copies the saved Alertmanager webhook URL.
- **Send Test Alert** posts a synthetic Alertmanager webhook to Cortex and should trigger History -> Supervisor -> Report.
- **Open incidents** jumps to the incident queue after sending or configuring alerts.
- **Copy YAML** copies the Alertmanager receiver snippet. Keep `send_resolved: true` so resolved notifications close Cortex incidents.
- **Copy curl** copies a manual webhook test command.
- **Save Polling** enables pull mode when Alertmanager cannot call Cortex. `history-agent` polls the configured Alertmanager `/api/v2/alerts` endpoint on the selected interval.
- **Poll Now** immediately reads active Alertmanager alerts and ingests only new alerts that Cortex has not already seen.
- **Reload** in Alertmanager API polling refreshes the saved poller config and latest poll status.
- **Save Mattermost** saves the Mattermost webhook, enabled state, channel override, bot username, and icon URL.
- **Send Mattermost Test** sends a test message through the saved Mattermost integration.
- **Reload** in Data integrations rereads the current observability and GitLab config from backend files.
- **Save Observability** saves Prometheus URL, Elasticsearch URL, and Elasticsearch index for `observability-agent` and Supervisor tools.
- **Test Prometheus** verifies the configured Prometheus URL.
- **Test Elasticsearch** verifies the configured Elasticsearch URL and index.
- **Save GitLab** saves GitLab URL, default project ID/path, and token for `repo-agent` and Supervisor tools.
- **Test GitLab** verifies the configured GitLab access.

### Agents page

Use this page to verify the stack from the browser.

- Health cards poll every 10 seconds for `history-agent`, `report-agent`, `supervisor-agent`, `observability-agent`, `repo-agent`, Prometheus, Alertmanager, Grafana, and node-exporter.
- **Raw detail** expands the exact health response or error text for a node.
- The healthy counter shows how many nodes are reachable through nginx.

### Cortex Models page

Use this page to control model routing and prompts while the app is running.

- Each agent card controls one LLM-backed agent route: supervisor, report, observability, and repo.
- **System prompt** expands the editable prompt sent to that agent model.
- **Provider** selects the model provider for that agent.
- **Model** selects one model from the provider's configured model list.
- **Save & reload config** writes agent routes and prompts to `config/llm_config.json` and reloads the visible config.
- **Test LLM call** sends a small test request through the selected provider/model for that agent.
- **Save Provider Settings** saves provider base URLs and HTTP/SOCKS proxy URLs. Use this to route OpenRouter through a proxy such as `http://185.255.89.232:5070`.
- **Save API Keys** writes pasted keys into the ignored runtime secret store; blank fields keep existing keys.
- **Refresh** reloads the current LLM config from the backend.

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
        +--> redis :6379
        |       - stores supervisor ReAct memory for 24 hours
        |
        +--> /api/supervisor/*, /api/config/*, /api/test-workflow
        |       |
        |       v
        |   supervisor-agent :8003
        |       - loads incident context from history-agent
        |       - runs a Thought -> Action -> Observation loop
        |       - can call query_observability against observability-agent
        |       - records recommended actions and safe lifecycle transitions
        |       - calls report-agent after queued analysis
        |
        +--> observability-agent :8003
        |       - exposes /api/v1/query, /api/v1/metrics/query, /api/v1/logs/errors
        |       - talks to Prometheus and Elasticsearch when configured
        |
        +--> repo-agent :8004
        |       - exposes /api/v1/repo/changes for GitLab commits/MRs
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
  - incident_knowledge stores approved root cause/resolution embeddings for RAG
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
| supervisor-agent | `8003` | `GET /health`, `GET /ready`, lifecycle/config APIs, `GET /api/v1/incidents/{id}/trace` |
| observability-agent | `8004` host -> `8003` container | `GET /health`, `POST /api/v1/query`, `POST /api/v1/metrics/query`, `GET /api/v1/logs/errors` |
| repo-agent | `8005` host -> `8004` container | `GET /health`, `GET /api/v1/repo/changes` |
| redis | `6379` (or `REDIS_PORT`) | ReAct memory store |
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
  - `GET /api/history/alertmanager/poll/config`
  - `PUT /api/history/alertmanager/poll/config`
  - `POST /api/history/alertmanager/poll/run`
  - `GET /api/history/alertmanager/poll/status`
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
  - `GET /api/supervisor/incidents/{incident_id}/trace`
  - `GET /api/supervisor/incidents/{incident_id}/similar`
  - `POST /api/supervisor/incidents/{incident_id}/approve`
  - `GET /api/config/llm`
  - `POST /api/config/llm`
  - `GET /api/config/llm/secrets`
  - `POST /api/config/llm/secrets`
  - `POST /api/config/llm/test/{agent}`
  - `POST /api/test-workflow`
- Observability and repo integrations
  - `GET /api/observability/health`
  - `GET /api/observability/api/v1/config`
  - `PUT /api/observability/api/v1/config`
  - `POST /api/observability/api/v1/test/prometheus`
  - `POST /api/observability/api/v1/test/elasticsearch`
  - `POST /api/observability/api/v1/analyze`
  - `POST /api/observability/api/v1/metrics/query`
  - `GET /api/observability/api/v1/logs/errors?service=<service>&minutes=60`
  - `GET /api/repo/health`
  - `GET /api/repo/api/v1/config`
  - `PUT /api/repo/api/v1/config`
  - `POST /api/repo/api/v1/test/gitlab`
  - `POST /api/repo/api/v1/analyze`
  - `GET /api/repo/api/v1/repo/changes`

### ReAct trace and integration UI

- `supervisor-agent` writes each ReAct step to Redis under the incident ID with a 24 hour TTL.
- Direct service endpoint: `GET http://<host>:8003/api/v1/incidents/{incident_id}/trace`.
- UI/API facade endpoint: `GET /api/supervisor/incidents/{incident_id}/trace`.
- The incident detail page polls this trace every 3 seconds while the incident status is `investigating`.
- The incident detail page also includes widgets for PromQL results, Elasticsearch error logs/stack traces, and recent GitLab commits/MRs.
- `observability-agent` and `repo-agent` have their own LLM routes and editable system prompts in `/settings`; supervisor calls their `/api/v1/analyze` endpoints as agent-to-agent tools.
- Cortex enforces a supervisor-first contract: observability-agent and repo-agent return specialist analysis to supervisor-agent, and report-agent writes the final report after Supervisor analysis.
- Human SREs can click **Approve & Learn** to edit the final root cause/resolution and save it to `incident_knowledge` for future retrieval.
- The `/integrations` page lets operators set Prometheus URL, Elasticsearch URL/index, GitLab URL/token/project, and run connection tests without rebuilding containers. These values are saved under `config/observability_integrations.json` and `config/repo_integrations.json` on the mounted config volume.

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
3. Click **Submit Endpoint Changes**. The UI saves this endpoint in browser storage and rebuilds the URL, YAML, and curl examples from the submitted values.
4. Copy the generated webhook URL, usually:

```text
http://<server-ip>:8080/api/alertmanager/webhook
```

5. Add it to Alertmanager:

```yaml
receivers:
  - name: sre-ai
    webhook_configs:
      - url: http://<server-ip>:8080/api/alertmanager/webhook
        send_resolved: true
```

Every firing Alertmanager alert is ingested by `history-agent`. The ingestion path queues `supervisor-agent`, and the supervisor queue worker generates a report after analysis, so the full History -> Supervisor -> Report workflow runs automatically.

Keep `send_resolved: true`. When Alertmanager sends a resolved notification, `history-agent` attaches that final alert to the matching incident and marks the incident `resolved` without running a new LLM workflow.

Pull active alerts from Alertmanager API:

1. Open `http://<server-ip>:8080/integrations`.
2. In **Alertmanager API polling**, enable pull mode.
3. Set **Alertmanager URL**, for example:

```text
https://alert.dr-msh.snpb.app
```

4. Keep the interval at `10` seconds or set any value between `5` and `300`.
5. Set a proxy only if the Cortex server needs one to reach Alertmanager.
6. Click **Save Polling**.
7. Click **Poll Now** to test immediately.

When enabled, `history-agent` calls `GET /api/v2/alerts?active=true&silenced=false&inhibited=false&unprocessed=true` on that Alertmanager URL every interval. New active alerts are converted into Cortex alerts with source `alertmanager-poll`, deduplicated by Alertmanager fingerprint/labels/start time, then the normal History -> Supervisor -> Report workflow starts. Duplicate active alerts are skipped, so polling every 10 seconds does not create repeated incidents for the same alert.

Each incident detail page includes a Cortex command log. It shows Supervisor as the brain/commander, includes History, Observability, Repo, and Report agent actions, exposes sanitized LLM traces and raw action details, and shows channel delivery records such as whether Mattermost delivery was sent, skipped, or failed. The same enriched data is available from `GET /api/report/{incident_id}/workflow-summary`.

Incidents and timeline events can be deleted from the UI when cleaning test data. Use the Incidents page delete button to remove an incident together with its alerts, timeline events, and queued actions, or open an incident and use `Delete event` on a single timeline entry. The matching APIs are `DELETE /api/history/incidents/{incident_id}` and `DELETE /api/history/incidents/{incident_id}/events/{event_id}`.

Connect Mattermost report delivery:

1. Open `http://<server-ip>:8080/integrations`.
2. Paste a Mattermost incoming webhook URL in the Mattermost delivery card.
3. Enable delivery, optionally set a channel override and bot username, then save.
4. Use **Send Mattermost Test** to verify the webhook.

When enabled, every newly generated report is posted by `report-agent` to Mattermost. Report storage does not depend on Mattermost availability; delivery failures are written to the dead-letter queue as `report.deliver_mattermost`.

Connect data sources for agent tools and incident widgets:

1. Open `http://<server-ip>:8080/integrations`.
2. In **Data integrations**, set `Prometheus URL`, `Elasticsearch URL`, and `Elasticsearch index`, then click **Save Observability**.
3. Set `GitLab URL`, `GitLab project ID/path`, and optionally a GitLab token, then click **Save GitLab**. Leave the token field blank on later saves to keep the existing token.
4. Use **Test Prometheus**, **Test Elasticsearch**, and **Test GitLab** to verify connectivity. A failed test returns a structured warning in the UI instead of crashing the agent.

The incident detail page uses these settings when fetching PromQL samples, recent error logs/stack traces, and recent GitLab commits/MRs. The supervisor's real ReAct tools also use the same observability-agent and repo-agent endpoints.

---

## LLM configuration and dynamic routing

`config/llm_config.json` is mounted to services via `LLM_CONFIG_PATH` and read by runtime.

You can:

- update routing through UI (`/settings`) with `POST /api/config/llm` for `supervisor`, `report`, `observability`, and `repo` agents
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
  - `HISTORY_AGENT_URL`, `REPORT_AGENT_URL`, `SUPERVISOR_AGENT_URL`, `OBSERVABILITY_AGENT_URL`, `REPO_AGENT_URL`
  - `PROMETHEUS_URL`, `ELASTICSEARCH_URL`, `GITLAB_URL`, `GITLAB_PROJECT_ID`
  - `REACT_MAX_ITERATIONS`, `REACT_MEMORY_TTL_SECONDS`
  - `VITE_API_BASE_URL` (defaults to `/api`)
- Security and ingestion behavior
  - `ALERT_WEBHOOK_SECRET` (optional webhook signature enforcement)
  - `ALERTMANAGER_URL`, `ALERTMANAGER_POLL_ENABLED`, `ALERTMANAGER_POLL_INTERVAL_SECONDS`
  - `ALERTMANAGER_POLL_TIMEOUT_SECONDS`, `ALERTMANAGER_POLL_VERIFY_TLS`, `ALERTMANAGER_POLL_PROXY_URL`
  - `ALERTMANAGER_POLL_CONFIG_PATH`
  - `MAX_ALERT_JSON_BYTES`, `MAX_ALERT_BATCH_SIZE`
  - `DEFAULT_SLA_HOURS`, `REOPEN_STALE_AFTER_HOURS`
- LLM and HTTP
  - `AI_PROVIDER`, `AI_MODEL`, provider keys/base URLs
  - `OPENROUTER_PROXY_URL`, `LLM_GATEWAY_PROXY_URL`, `GAPGPT_PROXY_URL`, `LLM_PROXY_URL`
  - `HTTP_TIMEOUT`, `HTTP_MAX_RETRIES`, `HTTP_BACKOFF_SECONDS`
  - `HTTP_CIRCUIT_BREAKER_THRESHOLD`, `HTTP_CIRCUIT_BREAKER_RESET_SECONDS`
  - `LLM_CONFIG_PATH`, `LLM_RUNTIME_SECRETS_PATH`
  - `GITLAB_TOKEN`
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

Phase 3 smoke/E2E flow:

```bash
python3 scripts/e2e_phase3_flow.py http://127.0.0.1:8080
```

This creates a synthetic incident, runs supervisor analysis, saves an approved root cause/resolution into pgvector-backed long-term memory, and verifies similar-incident retrieval.


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
