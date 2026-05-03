from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from integrations.elasticsearch_client import ELASTICSEARCH_URL, search_error_logs
from integrations.prometheus_client import PROMETHEUS_URL, query_prometheus


class QueryRequest(BaseModel):
    query: str = Field(default='up', max_length=500)
    datasource: str = Field(default='mock', max_length=80)
    incident_id: str | None = Field(default=None, max_length=120)


class MetricsQueryRequest(BaseModel):
    query: str = Field(default='up', max_length=1000)
    incident_id: str | None = Field(default=None, max_length=120)
    time: str | None = Field(default=None, max_length=80)


app = FastAPI(title='observability-agent', version='0.2.0')


@app.get('/health')
async def health() -> dict[str, Any]:
    return {
        'status': 'ok',
        'service': 'observability-agent',
        'prometheus_url': PROMETHEUS_URL,
        'elasticsearch_url': ELASTICSEARCH_URL,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.post('/api/v1/query')
async def query_observability(payload: QueryRequest) -> dict[str, Any]:
    return {
        'status': 'ok',
        'datasource': payload.datasource,
        'query': payload.query,
        'incident_id': payload.incident_id,
        'result_type': 'mock',
        'summary': 'Dummy observability response for ReAct supervisor tool testing.',
        'series': [
            {'metric': 'mock_error_rate', 'value': 0.02, 'unit': 'ratio'},
            {'metric': 'mock_p95_latency_ms', 'value': 420, 'unit': 'ms'},
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.post('/api/v1/metrics/query')
async def metrics_query(payload: MetricsQueryRequest) -> dict[str, Any]:
    try:
        data = await query_prometheus(payload.query, payload.time)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'prometheus query failed: {exc}') from exc
    return {
        'status': 'ok',
        'source': 'prometheus',
        'prometheus_url': PROMETHEUS_URL,
        'incident_id': payload.incident_id,
        'query': payload.query,
        'data': data.get('data', {}),
    }


@app.get('/api/v1/logs/errors')
async def logs_errors(
    service: str = Query(default='', max_length=160),
    minutes: int = Query(default=60, ge=1, le=1440),
) -> dict[str, Any]:
    try:
        return await search_error_logs(service, minutes=minutes)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'elasticsearch search failed: {exc}') from exc
