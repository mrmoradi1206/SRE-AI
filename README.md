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

## Dynamic LLM Routing

SRE-AI loads LLM provider/model routing from `config/llm_config.json` at runtime. The file is mounted into the agent containers at `/app/config/llm_config.json`, so changes through the UI or API are picked up without rebuilding or redeploying.

Supported providers:

- `openrouter` - OpenAI-compatible chat completions at `OPENROUTER_BASE_URL`.
- `llmgateway` - Snapp LLM Gateway OpenAI-compatible chat completions at `LLM_GATEWAY_BASE_URL`.
- `gapgpt` - GapGPT OpenAI-compatible chat completions at `GAPGPT_BASE_URL`.

Required secrets are provided through environment variables or the ignored runtime secret store and are never stored in `config/llm_config.json`:

```bash
OPENROUTER_API_KEY=...
LLM_GATEWAY_API_KEY=...
GAPGPT_API_KEY=...
```

The UI can update runtime API keys through `POST /api/config/llm/secrets`. Those values are written to `config/llm_runtime_secrets.json`, which is ignored by git and mounted into agent containers. For immutable production deploys, prefer environment or orchestrator-managed secrets.

The shared runtime client lives in `shared/aiops_shared/llm_client.py` and exposes:

```python
await run_llm(provider, model, messages, temperature=0.1)
```

All supervisor and report LLM calls route through this client. It handles provider selection, timeouts, retries, sanitized logging, and structured `LLMError` failures.

### LLM Config API

Through nginx:

- `GET /api/config/llm` - returns providers, models, and current per-agent routing.
- `POST /api/config/llm` - validates and saves provider/model routing.
- `GET /api/config/llm/secrets` - returns masked runtime secret status by provider.
- `POST /api/config/llm/secrets` - saves API keys to the ignored runtime secret store.
- `POST /api/config/llm/test/{agent}` - performs a real test LLM call for `supervisor` or `report`.
- `POST /api/test-workflow` - accepts a raw alert JSON payload and runs History -> Supervisor -> Report with sanitized trace output.

Example config:

```json
{
  "providers": ["openrouter", "llmgateway", "gapgpt"],
  "models": {
    "openrouter": ["meta-llama/llama-3.1-8b-instruct", "qwen/qwen-2.5-72b-instruct"],
    "llmgateway": ["zai/glm-5.1", "zai/glm-5", "minimax/MiniMax-M2.7", "kimi/kimi-k2.5"],
    "gapgpt": ["gapgpt-qwen-3.5", "gpt-4o", "gemini-2.5-pro"]
  },
  "provider_settings": {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY", "default_model": "openai/gpt-4o-mini"},
    "llmgateway": {"base_url": "https://llm.snapp.tech/v1", "api_key_env": "LLM_GATEWAY_API_KEY", "default_model": "zai/glm-5.1"},
    "gapgpt": {"base_url": "https://api.gapgpt.app/v1", "api_key_env": "GAPGPT_API_KEY", "default_model": "gapgpt-qwen-3.5"}
  },
  "agents": {
    "supervisor": {"provider": "llmgateway", "model": "zai/glm-5.1"},
    "report": {"provider": "openrouter", "model": "meta-llama/llama-3.1-8b-instruct"}
  }
}
```

The React UI includes an **LLM Settings** page for changing per-agent provider/model selections, editing runtime API keys, saving/reloading config, refreshing current config, and testing each agent route. The **Test Workflow** page accepts raw alert JSON and shows the full workflow result with sanitized LLM traces.

## Security Controls

- Alert ingestion can require `X-SRE-AI-Signature` or `X-Hub-Signature-256` HMAC-SHA256 when `ALERT_WEBHOOK_SECRET` is set.
- Alert payload size and batch size are capped by `MAX_ALERT_JSON_BYTES` and `MAX_ALERT_BATCH_SIZE`.
- LLM prompts treat alert payloads as untrusted data and LLM traces only include content previews, not API keys.
- Request IDs and correlation IDs are propagated across internal HTTP calls and returned in response headers.
