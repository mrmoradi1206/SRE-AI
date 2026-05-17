from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
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
