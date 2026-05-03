from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from integrations.config import load_config, save_config
from integrations.elasticsearch_client import search_error_logs
from integrations.prometheus_client import query_prometheus


class QueryRequest(BaseModel):
    query: str = Field(default='up', max_length=500)
    datasource: str = Field(default='mock', max_length=80)
    incident_id: str | None = Field(default=None, max_length=120)


class MetricsQueryRequest(BaseModel):
    query: str = Field(default='up', max_length=1000)
    incident_id: str | None = Field(default=None, max_length=120)
    time: str | None = Field(default=None, max_length=80)


class PrometheusConfig(BaseModel):
    url: str = Field(default='http://prometheus:9090', max_length=500)


class ElasticsearchConfig(BaseModel):
    url: str = Field(default='http://elasticsearch:9200', max_length=500)
    index: str = Field(default='logs-*', max_length=160)


class ObservabilityConfig(BaseModel):
    prometheus: PrometheusConfig = Field(default_factory=PrometheusConfig)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)


app = FastAPI(title='observability-agent', version='0.3.0')


def _current_urls() -> tuple[str, str, str]:
    config = load_config()
    prometheus_url = config.get('prometheus', {}).get('url', 'http://prometheus:9090')
    elasticsearch = config.get('elasticsearch', {})
    return prometheus_url, elasticsearch.get('url', 'http://elasticsearch:9200'), elasticsearch.get('index', 'logs-*')


@app.get('/health')
async def health() -> dict[str, Any]:
    prometheus_url, elasticsearch_url, elasticsearch_index = _current_urls()
    return {
        'status': 'ok',
        'service': 'observability-agent',
        'prometheus_url': prometheus_url,
        'elasticsearch_url': elasticsearch_url,
        'elasticsearch_index': elasticsearch_index,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.get('/api/v1/config')
async def get_config() -> dict[str, Any]:
    return load_config()


@app.put('/api/v1/config')
async def put_config(payload: ObservabilityConfig) -> dict[str, Any]:
    return save_config(payload.model_dump())


@app.post('/api/v1/test/prometheus')
async def test_prometheus() -> dict[str, Any]:
    prometheus_url, _, _ = _current_urls()
    try:
        data = await query_prometheus('up', prometheus_url=prometheus_url)
        return {'ok': True, 'prometheus_url': prometheus_url, 'data': data.get('data', {})}
    except httpx.HTTPError as exc:
        return {'ok': False, 'prometheus_url': prometheus_url, 'error': str(exc)}


@app.post('/api/v1/test/elasticsearch')
async def test_elasticsearch() -> dict[str, Any]:
    _, elasticsearch_url, index = _current_urls()
    try:
        data = await search_error_logs('', minutes=5, index=index, elasticsearch_url=elasticsearch_url)
        return {'ok': True, 'elasticsearch_url': elasticsearch_url, 'index': index, 'entries': data.get('entries', [])}
    except httpx.HTTPError as exc:
        return {'ok': False, 'elasticsearch_url': elasticsearch_url, 'index': index, 'error': str(exc)}


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
    prometheus_url, _, _ = _current_urls()
    try:
        data = await query_prometheus(payload.query, payload.time, prometheus_url=prometheus_url)
    except httpx.HTTPError as exc:
        return {'status': 'error', 'source': 'prometheus', 'prometheus_url': prometheus_url, 'error': str(exc), 'data': {}}
    return {
        'status': 'ok',
        'source': 'prometheus',
        'prometheus_url': prometheus_url,
        'incident_id': payload.incident_id,
        'query': payload.query,
        'data': data.get('data', {}),
    }


@app.get('/api/v1/logs/errors')
async def logs_errors(
    service: str = Query(default='', max_length=160),
    minutes: int = Query(default=60, ge=1, le=1440),
) -> dict[str, Any]:
    _, elasticsearch_url, index = _current_urls()
    try:
        return await search_error_logs(service, minutes=minutes, index=index, elasticsearch_url=elasticsearch_url)
    except httpx.HTTPError as exc:
        return {'status': 'error', 'service': service, 'minutes': minutes, 'index': index, 'entries': [], 'error': str(exc)}
