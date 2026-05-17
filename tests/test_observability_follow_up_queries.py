from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import asyncio
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
sys.path.insert(0, str(ROOT / 'services' / 'observability-agent'))

_SPEC = spec_from_file_location('observability_main_for_tests', ROOT / 'services' / 'observability-agent' / 'main.py')
observability_main = module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(observability_main)


def test_parse_recommended_queries_accepts_dict_like_values():
    content = """
    {
      "recommended_queries": [
        {"promql": "up"},
        "{\\"query\\": \\"rate(http_requests_total{job=~\\\\\\"api.*\\\\\\",status=~\\\\\\"5..\\\\\\"}[5m])\\"}",
        {"metrics_query": "sum(container_memory_working_set_bytes{container=~\\"api.*\\"})"}
      ]
    }
    """

    queries = observability_main._parse_recommended_queries(content)

    assert queries == [
        'up',
        'rate(http_requests_total{job=~"api.*",status=~"5.."}[5m])',
        'sum(container_memory_working_set_bytes{container=~"api.*"})',
    ]


def test_parse_recommended_queries_extracts_embedded_json_and_skips_invalid_values():
    content = """
    Here is the analysis:
    {
      "recommended_queries": [
        "https://example.com/not-promql",
        "curl http://example.com",
        "up",
        "sum(rate(http_requests_total{job=~\\"checkout.*\\"}[5m]))",
        {"query": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job=~\\"checkout.*\\"}[5m]))"}
      ]
    }
    """

    queries = observability_main._parse_recommended_queries(content)

    assert queries == [
        'up',
        'sum(rate(http_requests_total{job=~"checkout.*"}[5m]))',
        'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job=~"checkout.*"}[5m]))',
    ]


def test_collect_observability_skips_elasticsearch_when_disabled():
    original_load_config = observability_main.load_config
    original_query_prometheus = observability_main.query_prometheus

    async def fake_query_prometheus(query, time=None, prometheus_url=''):
        return {'data': {'resultType': 'vector', 'result': []}}

    observability_main.load_config = lambda: {
        'prometheus': {'url': 'http://prometheus:9090'},
        'victoriametrics': {'url': 'https://vm.example/api/v1', 'enabled': True},
        'metrics_datasource': 'victoriametrics',
        'elasticsearch': {'enabled': False, 'url': 'http://elasticsearch:9200', 'index': 'logs-*'},
    }
    observability_main.query_prometheus = fake_query_prometheus

    try:
        payload = observability_main.ObservabilityAnalyzeRequest(
            incident_id='test-incident',
            service='checkout-api',
            promql='up',
            minutes=30,
        )
        evidence = asyncio.run(observability_main._collect_observability(payload))
    finally:
        observability_main.load_config = original_load_config
        observability_main.query_prometheus = original_query_prometheus

    assert evidence['metrics']['status'] == 'ok'
    assert evidence['metrics']['source'] == 'victoriametrics'
    assert evidence['logs']['status'] == 'skipped'
    assert evidence['logs']['backend'] == 'elasticsearch'
