from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from aiops_shared.llm_client import LLMError, run_llm
from aiops_shared.llm_config import LLMConfigError, get_agent_llm_config, get_agent_system_prompt
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


class ObservabilityAnalyzeRequest(BaseModel):
    incident_id: str | None = Field(default=None, max_length=120)
    incident: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    service: str | None = Field(default=None, max_length=160)
    promql: str | None = Field(default=None, max_length=1000)
    minutes: int = Field(default=60, ge=1, le=1440)


class PrometheusConfig(BaseModel):
    url: str = Field(default='http://prometheus:9090', max_length=500)


class ElasticsearchConfig(BaseModel):
    url: str = Field(default='http://elasticsearch:9200', max_length=500)
    index: str = Field(default='logs-*', max_length=160)


class ObservabilityConfig(BaseModel):
    prometheus: PrometheusConfig = Field(default_factory=PrometheusConfig)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)


app = FastAPI(title='observability-agent', version='0.4.0')


def _current_urls() -> tuple[str, str, str]:
    config = load_config()
    prometheus_url = config.get('prometheus', {}).get('url', 'http://prometheus:9090')
    elasticsearch = config.get('elasticsearch', {})
    return prometheus_url, elasticsearch.get('url', 'http://elasticsearch:9200'), elasticsearch.get('index', 'logs-*')


def _safe_json(value: Any, limit: int = 16000) -> str:
    import json

    text = json.dumps(value, default=str)[:limit]
    return text


def _default_promql(service: str | None) -> str:
    if service and service != 'unknown':
        return f'up{{job=~"{service}.*"}}'
    return 'up'


async def _collect_observability(payload: ObservabilityAnalyzeRequest) -> dict[str, Any]:
    prometheus_url, elasticsearch_url, index = _current_urls()
    service = payload.service or 'unknown'
    promql = payload.promql or _default_promql(service)
    metrics: dict[str, Any]
    logs: dict[str, Any]
    try:
        metrics_data = await query_prometheus(promql, prometheus_url=prometheus_url)
        metrics = {'status': 'ok', 'prometheus_url': prometheus_url, 'query': promql, 'data': metrics_data.get('data', {})}
    except httpx.HTTPError as exc:
        metrics = {'status': 'error', 'prometheus_url': prometheus_url, 'query': promql, 'error': str(exc), 'data': {}}
    try:
        logs = await search_error_logs(service if service != 'unknown' else '', minutes=payload.minutes, index=index, elasticsearch_url=elasticsearch_url)
        logs['elasticsearch_url'] = elasticsearch_url
    except httpx.HTTPError as exc:
        logs = {'status': 'error', 'service': service, 'minutes': payload.minutes, 'index': index, 'entries': [], 'error': str(exc), 'elasticsearch_url': elasticsearch_url}
    return {'service': service, 'metrics': metrics, 'logs': logs}


@app.get('/health')
async def health() -> dict[str, Any]:
    prometheus_url, elasticsearch_url, elasticsearch_index = _current_urls()
    return {
        'status': 'ok',
        'service': 'observability-agent',
        'llm_enabled': True,
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


@app.post('/api/v1/analyze')
async def analyze_observability(payload: ObservabilityAnalyzeRequest) -> dict[str, Any]:
    evidence = await _collect_observability(payload)
    try:
        selection = get_agent_llm_config('observability')
        response = await run_llm(
            selection['provider'],
            selection['model'],
            [
                {'role': 'system', 'content': get_agent_system_prompt('observability')},
                {'role': 'user', 'content': _safe_json({'task': 'Analyze observability evidence and respond with strict JSON.', 'request': payload.model_dump(), 'evidence': evidence})},
            ],
            temperature=0.1,
            max_tokens=700,
        )
        return {'status': 'ok', 'agent': 'observability-agent', 'provider': response['provider'], 'model': response['model'], 'analysis': response['content'], 'evidence': evidence, 'llm_trace': response.get('trace')}
    except (LLMConfigError, LLMError) as exc:
        return {'status': 'fallback', 'agent': 'observability-agent', 'analysis': 'LLM analysis unavailable; returning collected metrics/log evidence only.', 'error': str(exc), 'evidence': evidence}


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
