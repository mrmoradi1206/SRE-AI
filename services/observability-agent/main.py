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
    datasource: str | None = Field(default=None, max_length=32)


class ObservabilityAnalyzeRequest(BaseModel):
    incident_id: str | None = Field(default=None, max_length=120)
    incident: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    service: str | None = Field(default=None, max_length=160)
    promql: str | None = Field(default=None, max_length=1000)
    minutes: int = Field(default=60, ge=1, le=1440)


class PrometheusConfig(BaseModel):
    url: str = Field(default='http://prometheus:9090', max_length=500)


class VictoriaMetricsConfig(BaseModel):
    url: str = Field(default='http://victoriametrics:8428', max_length=500)
    enabled: bool = Field(default=False)


class ElasticsearchConfig(BaseModel):
    enabled: bool = Field(default=False)
    url: str = Field(default='http://elasticsearch:9200', max_length=500)
    index: str = Field(default='logs-*', max_length=160)


class ObservabilityConfig(BaseModel):
    prometheus: PrometheusConfig = Field(default_factory=PrometheusConfig)
    victoriametrics: VictoriaMetricsConfig = Field(default_factory=VictoriaMetricsConfig)
    metrics_datasource: str = Field(default='prometheus', max_length=32)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)


app = FastAPI(title='observability-agent', version='0.4.0')


def _current_urls() -> tuple[str, str, str, str, bool, str, bool]:
    config = load_config()
    prometheus_url = config.get('prometheus', {}).get('url', 'http://prometheus:9090')
    vm_config = config.get('victoriametrics', {})
    vm_url = vm_config.get('url', 'http://victoriametrics:8428')
    vm_enabled = bool(vm_config.get('enabled', False))
    metrics_datasource = str(config.get('metrics_datasource', 'prometheus')).lower()
    elasticsearch = config.get('elasticsearch', {})
    return (
        prometheus_url,
        vm_url,
        metrics_datasource,
        elasticsearch.get('url', 'http://elasticsearch:9200'),
        vm_enabled,
        elasticsearch.get('index', 'logs-*'),
        bool(elasticsearch.get('enabled', False)),
    )


def _metrics_target(prometheus_url: str, vm_url: str, default_datasource: str, requested_datasource: str | None, vm_enabled: bool) -> tuple[str, str]:
    source = (requested_datasource or default_datasource or 'prometheus').lower()
    if source in {'victoria', 'victoriametrics', 'vm'}:
        if vm_enabled:
            return 'victoriametrics', vm_url
        return 'prometheus', prometheus_url
    return 'prometheus', prometheus_url


def _safe_json(value: Any, limit: int = 16000) -> str:
    import json

    text = json.dumps(value, default=str)[:limit]
    return text


def _default_promql(service: str | None) -> str:
    if service and service != 'unknown':
        return f'up{{job=~"{service}.*"}}'
    return 'up'


async def _collect_observability(payload: ObservabilityAnalyzeRequest) -> dict[str, Any]:
    prometheus_url, vm_url, metrics_datasource, elasticsearch_url, vm_enabled, index, elasticsearch_enabled = _current_urls()
    service = payload.service or 'unknown'
    promql = payload.promql or _default_promql(service)
    metrics: dict[str, Any]
    logs: dict[str, Any]
    try:
        source, base_url = _metrics_target(prometheus_url, vm_url, metrics_datasource, None, vm_enabled)
        metrics_data = await query_prometheus(promql, prometheus_url=base_url)
        metrics = {'status': 'ok', 'source': source, 'metrics_url': base_url, 'query': promql, 'data': metrics_data.get('data', {})}
    except httpx.HTTPError as exc:
        metrics = {'status': 'error', 'query': promql, 'error': str(exc), 'data': {}}
    if not elasticsearch_enabled:
        logs = {
            'status': 'skipped',
            'backend': 'elasticsearch',
            'service': service,
            'minutes': payload.minutes,
            'reason': 'Elasticsearch log collection is disabled in observability config.',
        }
    else:
        try:
            logs = await search_error_logs(service if service != 'unknown' else '', minutes=payload.minutes, index=index, elasticsearch_url=elasticsearch_url)
            logs['elasticsearch_url'] = elasticsearch_url
        except httpx.HTTPError as exc:
            logs = {'status': 'error', 'service': service, 'minutes': payload.minutes, 'index': index, 'entries': [], 'error': str(exc), 'elasticsearch_url': elasticsearch_url}
    return {'service': service, 'metrics': metrics, 'logs': logs}


@app.get('/health')
async def health() -> dict[str, Any]:
    prometheus_url, vm_url, metrics_datasource, elasticsearch_url, vm_enabled, elasticsearch_index, elasticsearch_enabled = _current_urls()
    return {
        'status': 'ok',
        'service': 'observability-agent',
        'llm_enabled': True,
        'prometheus_url': prometheus_url,
        'victoriametrics_url': vm_url,
        'victoriametrics_enabled': vm_enabled,
        'metrics_datasource': metrics_datasource,
        'elasticsearch_enabled': elasticsearch_enabled,
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
    prometheus_url, _, _, _, _, _, _ = _current_urls()
    try:
        data = await query_prometheus('up', prometheus_url=prometheus_url)
        return {'ok': True, 'prometheus_url': prometheus_url, 'data': data.get('data', {})}
    except httpx.HTTPError as exc:
        return {'ok': False, 'prometheus_url': prometheus_url, 'error': str(exc)}


@app.post('/api/v1/test/victoriametrics')
async def test_victoriametrics() -> dict[str, Any]:
    _, vm_url, _, _, vm_enabled, _, _ = _current_urls()
    if not vm_enabled:
        return {'ok': False, 'victoriametrics_url': vm_url, 'error': 'VictoriaMetrics is disabled in observability config.'}
    try:
        data = await query_prometheus('up', prometheus_url=vm_url)
        return {'ok': True, 'victoriametrics_url': vm_url, 'data': data.get('data', {})}
    except httpx.HTTPError as exc:
        return {'ok': False, 'victoriametrics_url': vm_url, 'error': str(exc)}


@app.post('/api/v1/test/elasticsearch')
async def test_elasticsearch() -> dict[str, Any]:
    _, _, _, elasticsearch_url, _, index, elasticsearch_enabled = _current_urls()
    if not elasticsearch_enabled:
        return {'ok': False, 'enabled': False, 'error': 'Elasticsearch is disabled in observability config.'}
    try:
        data = await search_error_logs('', minutes=5, index=index, elasticsearch_url=elasticsearch_url)
        return {'ok': True, 'elasticsearch_url': elasticsearch_url, 'index': index, 'entries': data.get('entries', [])}
    except httpx.HTTPError as exc:
        return {'ok': False, 'elasticsearch_url': elasticsearch_url, 'index': index, 'error': str(exc)}


def _parse_recommended_queries(analysis_content: str) -> list[str]:
    try:
        import ast
        import json
        import re

        text = analysis_content.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text, re.IGNORECASE)
            text = re.sub(r'\s*```$', '', text)

        def _looks_like_promql(query: str) -> bool:
            value = str(query).strip().lower()
            if not value:
                return False
            if any(token in value for token in ('http://', 'https://', 'curl ', 'get ', 'post ', 'put ', 'delete ')):
                return False
            if re.fullmatch(r'[a-z_:][a-z0-9_:]*', value):
                return True
            if any(marker in value for marker in (' up', 'up{', '{', '}', '(', ')', 'rate(', 'histogram_quantile(', 'sum(', 'avg(')):
                return True
            return False

        def _normalize_query(raw: Any) -> str | None:
            if isinstance(raw, str):
                stripped = raw.strip()
                if stripped.startswith('{') and stripped.endswith('}'):
                    try:
                        parsed_item = json.loads(stripped)
                    except Exception:
                        parsed_item = None
                    if parsed_item is None:
                        try:
                            parsed_item = ast.literal_eval(stripped)
                        except Exception:
                            parsed_item = None
                    if isinstance(parsed_item, dict):
                        candidate = parsed_item.get('promql') or parsed_item.get('query') or parsed_item.get('metrics_query')
                        if isinstance(candidate, str) and _looks_like_promql(candidate):
                            return candidate.strip()
                return stripped if _looks_like_promql(stripped) else None
            if isinstance(raw, dict):
                candidate = raw.get('promql') or raw.get('query') or raw.get('metrics_query')
                if isinstance(candidate, str) and _looks_like_promql(candidate):
                    return candidate.strip()
            return None

        def _parse_payload(raw_text: str) -> dict[str, Any] | None:
            try:
                parsed_payload = json.loads(raw_text)
            except Exception:
                parsed_payload = None
            if isinstance(parsed_payload, dict):
                return parsed_payload
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if not match:
                return None
            try:
                parsed_payload = json.loads(match.group(0))
            except Exception:
                return None
            return parsed_payload if isinstance(parsed_payload, dict) else None

        parsed = _parse_payload(text)
        queries = parsed.get('recommended_queries', []) if isinstance(parsed, dict) else []
        if isinstance(queries, (str, dict)):
            queries = [queries]
        if isinstance(queries, list):
            output: list[str] = []
            for query in queries:
                candidate = _normalize_query(query)
                if candidate:
                    output.append(candidate)
                if len(output) >= 3:
                    break
            return output
    except Exception:
        pass
    return []


@app.post('/api/v1/analyze')
async def analyze_observability(payload: ObservabilityAnalyzeRequest) -> dict[str, Any]:
    prometheus_url, vm_url, metrics_datasource, elasticsearch_url, vm_enabled, index, _ = _current_urls()
    evidence = await _collect_observability(payload)
    selection = get_agent_llm_config('observability')

    try:
        round1 = await run_llm(
            selection['provider'],
            selection['model'],
            [
                {'role': 'system', 'content': get_agent_system_prompt('observability')},
                {
                    'role': 'user',
                    'content': _safe_json(
                        {
                            'task': 'Analyze initial observability evidence. If you need more data, list PromQL queries in recommended_queries. Respond with strict JSON.',
                            'request': payload.model_dump(),
                            'evidence': evidence,
                        }
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=700,
        )

        follow_up_queries = _parse_recommended_queries(round1['content'])
        additional_evidence: list[dict] = []
        if follow_up_queries:
            _, base_url = _metrics_target(prometheus_url, vm_url, metrics_datasource, None, vm_enabled)
            import asyncio as _asyncio

            async def _run_query(promql: str) -> dict:
                try:
                    data = await query_prometheus(promql, prometheus_url=base_url)
                    return {'query': promql, 'status': 'ok', 'data': data.get('data', {})}
                except Exception as exc:  # noqa: BLE001
                    return {'query': promql, 'status': 'error', 'error': str(exc)}

            additional_evidence = await _asyncio.gather(*[_run_query(query) for query in follow_up_queries])

        if additional_evidence:
            final_response = await run_llm(
                selection['provider'],
                selection['model'],
                [
                    {'role': 'system', 'content': get_agent_system_prompt('observability')},
                    {
                        'role': 'user',
                        'content': _safe_json(
                            {
                                'task': 'Synthesize all observability evidence (initial + follow-up queries) into a final analysis. Respond with strict JSON.',
                                'request': payload.model_dump(),
                                'initial_evidence': evidence,
                                'initial_analysis': round1['content'],
                                'follow_up_evidence': list(additional_evidence),
                            }
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=800,
            )
            return {
                'status': 'ok',
                'agent': 'observability-agent',
                'provider': final_response['provider'],
                'model': final_response['model'],
                'analysis': final_response['content'],
                'evidence': evidence,
                'follow_up_queries': follow_up_queries,
                'follow_up_evidence': list(additional_evidence),
                'rounds': 2,
                'llm_trace': final_response.get('trace'),
            }

        return {
            'status': 'ok',
            'agent': 'observability-agent',
            'provider': round1['provider'],
            'model': round1['model'],
            'analysis': round1['content'],
            'evidence': evidence,
            'follow_up_queries': [],
            'rounds': 1,
            'llm_trace': round1.get('trace'),
        }

    except (LLMConfigError, LLMError) as exc:
        return {
            'status': 'fallback',
            'agent': 'observability-agent',
            'analysis': 'LLM analysis unavailable; returning collected metrics/log evidence only.',
            'error': str(exc),
            'evidence': evidence,
            'rounds': 0,
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
    prometheus_url, vm_url, metrics_datasource, _, vm_enabled, _, _ = _current_urls()
    source, base_url = _metrics_target(prometheus_url, vm_url, metrics_datasource, payload.datasource, vm_enabled)
    try:
        data = await query_prometheus(payload.query, payload.time, prometheus_url=base_url)
    except httpx.HTTPError as exc:
        return {'status': 'error', 'source': source, 'metrics_url': base_url, 'error': str(exc), 'data': {}}
    return {
        'status': 'ok',
        'source': source,
        'metrics_url': base_url,
        'incident_id': payload.incident_id,
        'query': payload.query,
        'data': data.get('data', {}),
    }


@app.get('/api/v1/logs/errors')
async def logs_errors(
    service: str = Query(default='', max_length=160),
    minutes: int = Query(default=60, ge=1, le=1440),
) -> dict[str, Any]:
    _, _, _, elasticsearch_url, _, index, elasticsearch_enabled = _current_urls()
    if not elasticsearch_enabled:
        return {
            'status': 'skipped',
            'backend': 'elasticsearch',
            'service': service,
            'minutes': minutes,
            'reason': 'Elasticsearch log collection is disabled in observability config.',
        }
    try:
        return await search_error_logs(service, minutes=minutes, index=index, elasticsearch_url=elasticsearch_url)
    except httpx.HTTPError as exc:
        return {'status': 'error', 'service': service, 'minutes': minutes, 'index': index, 'entries': [], 'error': str(exc)}
