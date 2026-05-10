from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import OBSERVABILITY_AGENT_URL, REPO_AGENT_URL


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    when_to_use: str
    endpoint: str
    input_schema: dict[str, Any]
    timeout: float = 8.0


AGENT_REGISTRY: dict[str, AgentSpec] = {
    'query_observability': AgentSpec(
        name='query_observability',
        description='Fetch metrics, logs, and traces for the affected service from Prometheus, VictoriaMetrics, and Elasticsearch.',
        when_to_use='Use when the alert involves CPU, memory, latency, error rate, saturation, availability, or any metric/log-based signal.',
        endpoint=f'{OBSERVABILITY_AGENT_URL.rstrip("/")}/api/v1/analyze',
        input_schema={'promql': 'optional PromQL string', 'minutes': 'optional lookback window in minutes'},
    ),
    'query_repo_changes': AgentSpec(
        name='query_repo_changes',
        description='Fetch recent deployments, commits, and merge requests for the affected service from GitLab.',
        when_to_use='Use when the alert started after a deploy, a code/config change could explain the issue, or rollback context is needed.',
        endpoint=f'{REPO_AGENT_URL.rstrip("/")}/api/v1/analyze',
        input_schema={'project_id': 'optional GitLab project path or ID', 'ref': 'optional branch/ref', 'days': 'optional lookback days'},
    ),
}


MEMORY_TOOL_SPEC = {
    'name': 'query_memory',
    'description': "Search this incident's previous observations and ReAct trace from short-term Redis memory.",
    'when_to_use': 'Use when you want to recall what was already investigated in this incident before choosing another tool.',
    'input_schema': {'limit': 'optional max memory entries to return'},
}


def get_registry_for_prompt() -> list[dict[str, Any]]:
    return [
        {
            'name': spec.name,
            'description': spec.description,
            'when_to_use': spec.when_to_use,
            'input_schema': spec.input_schema,
        }
        for spec in AGENT_REGISTRY.values()
    ] + [MEMORY_TOOL_SPEC]
