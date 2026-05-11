import json
import logging
import re
from typing import Any

import httpx

from aiops_shared.context_loader import normalize_incident_bundle
from aiops_shared.llm_client import run_llm
from aiops_shared.llm_config import get_agent_system_prompt
from aiops_shared.database import get_session_factory

from .agent_registry import AGENT_REGISTRY, get_registry_for_prompt
from .config import REACT_MAX_ITERATIONS
from .memory import ReActMemory
from .rag import IncidentRAG

logger = logging.getLogger(__name__)

# Patterns that commonly indicate prompt injection attempts in alert payloads
_INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(all\s+)?(previous\s+|above\s+|prior\s+)?instructions?', re.IGNORECASE),
    re.compile(r'forget\s+(all\s+)?(previous\s+|above\s+)?(instructions?|context|prompt)', re.IGNORECASE),
    re.compile(r'you\s+are\s+now\s+(a\s+)?', re.IGNORECASE),
    re.compile(r'system\s*:\s*you\s+are', re.IGNORECASE),
    re.compile(r'\{\{\s*.*?\s*\}\}'),  # Jinja/template injection attempts
    re.compile(r'<\s*script\s*>', re.IGNORECASE),
    re.compile(r'new\s+instruction\s*:', re.IGNORECASE),
]

_MAX_STRING_LENGTH = 4096
_MAX_ALERT_PAYLOAD_KEYS = 64
_MAX_ALERT_PAYLOAD_DEPTH = 4


def _sanitize_string(value: str) -> str:
    if not isinstance(value, str):
        return value
    # Strip control characters except newlines/tabs
    cleaned = ''.join(ch for ch in value if ch == '\n' or ch == '\t' or (ord(ch) >= 32 and ord(ch) <= 126))
    # Truncate to limit
    return cleaned[:_MAX_STRING_LENGTH]


def _sanitize_value(value, depth: int = 0):
    if depth > _MAX_ALERT_PAYLOAD_DEPTH:
        return '[nested-too-deep]'
    if isinstance(value, str):
        sanitized = _sanitize_string(value)
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(sanitized):
                logger.warning('prompt_injection_attempt_detected', extra={'matched_pattern': pattern.pattern[:60], 'preview': sanitized[:200]})
                return '[sanitized-prompt-injection-attempt]'
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, depth + 1) for item in value[:100]]  # limit list items
    if isinstance(value, dict):
        if len(value) > _MAX_ALERT_PAYLOAD_KEYS:
            logger.warning('alert_payload_keys_truncated', extra={'original_keys': len(value)})
        return {
            _sanitize_string(str(k))[:128]: _sanitize_value(v, depth + 1)
            for k, v in list(value.items())[:_MAX_ALERT_PAYLOAD_KEYS]
        }
    return value


def _sanitize_bundle(bundle: dict) -> dict:
    incident = bundle.get('incident', {})
    alerts = bundle.get('alerts', [])
    timeline = bundle.get('timeline', [])
    similar = bundle.get('similar_incidents', [])

    sanitized_incident = _sanitize_value(incident)
    sanitized_alerts = [_sanitize_value(alert) for alert in alerts[:20]]
    sanitized_timeline = [_sanitize_value(event) for event in timeline[:40]]
    sanitized_similar = [_sanitize_value(sim) for sim in similar[:5]]

    return {
        'incident': sanitized_incident,
        'alerts': sanitized_alerts,
        'timeline': sanitized_timeline,
        'similar_incidents': sanitized_similar,
    }


class CMDBEnricher:
    def enrich(self, incident_bundle: dict) -> dict:
        incident = normalize_incident_bundle(incident_bundle).get('incident', {})
        return {
            'service_tier': 'gold' if incident.get('severity') in {'critical', 'high'} else 'silver',
            'owning_team': 'platform-sre',
            'runbook_url': 'https://runbooks.example.local/sre-ai/incident-response',
        }


class SupervisorAdvisor:
    def __init__(self) -> None:
        self.cmdb = CMDBEnricher()
        self.memory = ReActMemory()
        self.rag = IncidentRAG()

    def _service_name(self, incident_bundle: dict) -> str:
        bundle = normalize_incident_bundle(incident_bundle)
        incident = bundle.get('incident', {})
        alerts = bundle.get('alerts', [])
        latest_payload = alerts[-1].get('payload', {}) if alerts else {}
        labels = latest_payload.get('labels', {}) if isinstance(latest_payload, dict) else {}
        return labels.get('service') or labels.get('job') or labels.get('app') or labels.get('alertname') or incident.get('summary') or 'unknown'

    async def query_observability(self, incident_bundle: dict, query: str | dict | None = None) -> dict:
        bundle = normalize_incident_bundle(incident_bundle)
        incident = bundle.get('incident', {})
        alerts = bundle.get('alerts', [])
        incident_id = str(incident.get('id') or '')
        service = self._service_name(incident_bundle)

        latest_alert = alerts[-1] if alerts else {}
        latest_payload = latest_alert.get('payload', {}) if isinstance(latest_alert.get('payload'), dict) else {}
        labels = latest_payload.get('labels', {}) if isinstance(latest_payload, dict) else {}

        alert_name = labels.get('alertname', '')
        severity = (labels.get('severity') or incident.get('severity') or 'unknown').lower()

        first_seen_at = incident.get('first_seen_at') or incident.get('last_seen_at')
        minutes = 60
        if first_seen_at:
            try:
                from datetime import datetime, timezone

                start = datetime.fromisoformat(str(first_seen_at).replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                elapsed = int((now - start).total_seconds() / 60)
                minutes = max(30, min(elapsed + 30, 360))
            except Exception:
                minutes = 60

        promql = query.get('promql') if isinstance(query, dict) else query
        if not promql and alert_name:
            alert_name_lower = alert_name.lower()
            if any(keyword in alert_name_lower for keyword in ('latency', 'duration', 'p99', 'p95')):
                promql = f'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{{job=~"{service}.*"}}[5m]))'
            elif any(keyword in alert_name_lower for keyword in ('error', 'fail', '5xx', '4xx')):
                promql = f'rate(http_requests_total{{job=~"{service}.*",status=~"5.."}}[5m])'
            elif any(keyword in alert_name_lower for keyword in ('memory', 'mem', 'heap', 'oom')):
                promql = f'container_memory_working_set_bytes{{container=~"{service}.*"}}'
            elif any(keyword in alert_name_lower for keyword in ('cpu',)):
                promql = f'rate(container_cpu_usage_seconds_total{{container=~"{service}.*"}}[5m])'
            else:
                promql = f'up{{job=~"{service}.*"}}' if service and service != 'unknown' else 'up'
        elif not promql:
            promql = f'up{{job=~"{service}.*"}}' if service and service != 'unknown' else 'up'

        observations: dict[str, Any] = {
            'tool': 'query_observability',
            'source': 'observability-agent',
            'service': service,
        }
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                analysis_response = await client.post(
                    AGENT_REGISTRY['query_observability'].endpoint,
                    json={
                        'incident_id': incident_id,
                        'incident': incident,
                        'alerts': alerts[:10],
                        'service': service,
                        'promql': str(promql),
                        'minutes': minutes,
                        'alert_name': alert_name,
                        'severity': severity,
                        'alert_started_at': str(first_seen_at or ''),
                    },
                )
                analysis_response.raise_for_status()
                observations['agent_response'] = analysis_response.json()
            observations['summary'] = (
                f'Observability analysis for {service} '
                f'(alert={alert_name}, window={minutes}min, severity={severity}).'
            )
            return observations
        except Exception as exc:  # noqa: BLE001
            logger.warning('query_observability_failed', extra={'error_type': type(exc).__name__})
            return {
                'tool': 'query_observability',
                'source': 'error',
                'service': service,
                'error': type(exc).__name__,
                'summary': 'Observability lookup failed; continue with incident context.',
            }

    async def query_repo_changes(self, incident_bundle: dict, query: str | dict | None = None) -> dict:
        bundle = normalize_incident_bundle(incident_bundle)
        incident = bundle.get('incident', {})
        alerts = bundle.get('alerts', [])

        project_id = query.get('project_id') if isinstance(query, dict) else None
        ref = query.get('ref') if isinstance(query, dict) else None

        first_seen_at = incident.get('first_seen_at') or incident.get('last_seen_at')
        days = 2
        alert_started_at = ''
        if first_seen_at:
            try:
                from datetime import datetime, timezone

                start = datetime.fromisoformat(str(first_seen_at).replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                elapsed_days = (now - start).total_seconds() / 86400
                days = max(1, min(int(elapsed_days) + 1, 7))
                alert_started_at = start.isoformat()
            except Exception:
                days = 2

        params: dict[str, Any] = {'days': days, 'limit': 10}
        if project_id:
            params['project_id'] = project_id
        if ref:
            params['ref'] = ref

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(
                    AGENT_REGISTRY['query_repo_changes'].endpoint,
                    json={
                        'incident_id': str(incident.get('id') or ''),
                        'incident': incident,
                        'alerts': alerts[:10],
                        'service': self._service_name(incident_bundle),
                        'alert_started_at': alert_started_at,
                        **params,
                    },
                )
            response.raise_for_status()
            result = response.json()
            result['tool'] = 'query_repo_changes'
            result['source'] = 'repo-agent'
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning('query_repo_changes_failed', extra={'error_type': type(exc).__name__})
            return {
                'tool': 'query_repo_changes',
                'source': 'error',
                'error': type(exc).__name__,
                'summary': 'Repo lookup failed or GitLab project is not configured.',
            }

    async def _run_action(self, incident_bundle: dict, action: dict[str, Any]) -> dict:
        name = action.get('name')
        if name in {'query_observability', 'query_metrics', 'search_logs'}:
            return await self.query_observability(incident_bundle, action.get('input'))
        if name in {'query_repo_changes', 'get_repo_changes'}:
            return await self.query_repo_changes(incident_bundle, action.get('input'))
        if name == 'query_memory':
            incident_id = self._incident_id(incident_bundle)
            limit = 20
            action_input = action.get('input')
            if isinstance(action_input, dict):
                try:
                    limit = max(1, min(50, int(action_input.get('limit', limit))))
                except (TypeError, ValueError):
                    limit = 20
            history = await self.memory.get_history(incident_id, limit=limit)
            return {
                'tool': 'query_memory',
                'source': 'supervisor-memory',
                'history': history,
                'summary': f'Retrieved {len(history)} memory entries for this incident.',
            }
        return {'tool': name or 'unknown', 'source': 'error', 'error': 'unknown tool'}

    def _incident_id(self, incident_bundle: dict) -> str:
        incident = normalize_incident_bundle(incident_bundle).get('incident', {})
        return str(incident.get('id') or incident.get('fingerprint') or 'unknown')

    def build_fallback_decision(self, incident_bundle: dict, settings: dict, reasoning_mode: str = 'balanced') -> dict:
        bundle = normalize_incident_bundle(incident_bundle)
        alerts = bundle.get('alerts', [])
        incident = bundle['incident']
        latest_payload = alerts[-1]['payload'] if alerts else {}
        labels = latest_payload.get('labels', {}) if isinstance(latest_payload, dict) else {}
        severity = (labels.get('severity') or latest_payload.get('severity') or incident.get('severity') or 'unknown').lower()
        repeated_alerts = len(alerts)
        active_sources = len({alert.get('source') for alert in alerts if alert.get('source')})
        enrichment = self.cmdb.enrich(incident_bundle)

        next_state = incident['status']
        confidence = 0.45
        root_cause = f"Possible issue around {labels.get('alertname', incident.get('summary') or 'unknown condition')}"
        recommended_actions = [
            {'priority': 1, 'action': 'Inspect recent logs and metrics for the affected service'},
            {'priority': 2, 'action': 'Consult service runbook and validate blast radius'},
        ]
        reasoning_trace = [
            f"severity={severity}",
            f"alert_count={repeated_alerts}",
            f"active_sources={active_sources}",
            f"current_status={incident['status']}",
            f"reasoning_mode={reasoning_mode}",
            f"service_tier={enrichment['service_tier']}",
        ]

        if incident['status'] in {'resolved', 'closed'}:
            confidence = 0.99
            root_cause = 'Incident already terminal; no further action required.'
        elif severity == 'critical' or repeated_alerts >= 4:
            next_state = 'investigating' if incident['status'] == 'open' else 'mitigating'
            confidence = 0.88
            root_cause = 'Critical severity or repeated alert burst indicates active degradation.'
            recommended_actions.append({'priority': 3, 'action': 'Page owning team and start mitigation plan'})
        elif incident['status'] == 'mitigating' and severity in {'low', 'medium'} and repeated_alerts <= 1:
            next_state = 'resolved'
            confidence = 0.74
            root_cause = 'Signal has stabilized after mitigation.'
        elif incident['status'] == 'open':
            next_state = 'investigating'
            confidence = 0.63
            root_cause = 'Fresh signal warrants investigation before mitigation.'

        return {
            'root_cause': root_cause,
            'confidence': max(0.0, min(1.0, confidence)),
            'recommended_actions': recommended_actions,
            'next_state': next_state,
            'reasoning_trace': ' | '.join(reasoning_trace),
            'provider': settings['provider'],
            'model': settings['model'],
            'context_enrichment': enrichment,
        }

    def _coerce_final_decision(self, raw: dict[str, Any], fallback: dict) -> dict:
        decision = raw.get('final') if isinstance(raw.get('final'), dict) else raw
        return {
            'root_cause': decision.get('root_cause', fallback['root_cause']),
            'confidence': float(decision.get('confidence', fallback['confidence'])),
            'recommended_actions': decision.get('recommended_actions', fallback['recommended_actions']),
            'next_state': decision.get('next_state', fallback['next_state']),
            'reasoning_trace': decision.get('reasoning_trace', fallback['reasoning_trace']),
            'needs_human': bool(decision.get('needs_human', fallback.get('needs_human', False))),
            'human_request': str(decision.get('human_request', fallback.get('human_request', '')) or ''),
        }

    def _parse_react_step(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s*```$', '', text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _summarize_observation(self, observation: dict[str, Any]) -> str:
        if not isinstance(observation, dict):
            return 'No observation captured.'
        if observation.get('source') == 'observability-agent':
            agent_response = observation.get('agent_response', {})
            return str(agent_response.get('analysis') or observation.get('summary') or 'Collected metrics and logs evidence.')
        if observation.get('source') == 'repo-agent':
            return str(observation.get('analysis') or observation.get('summary') or 'Collected repository change evidence.')
        if observation.get('error'):
            return f"Tool call failed ({observation.get('error')})."
        return str(observation.get('summary') or 'Observation recorded.')

    async def answer_question(self, incident_bundle: dict, question: str, settings: dict[str, Any]) -> dict[str, Any]:
        incident_id = self._incident_id(incident_bundle)
        bundle = _sanitize_bundle(normalize_incident_bundle(incident_bundle))
        react_trace: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        llm_traces: list[dict[str, Any]] = []
        answer = 'I could not produce a confident answer yet.'
        confidence = 'medium'
        next_actions: list[Any] = []
        provider = settings.get('provider')
        model = settings.get('model')
        llm_trace: dict[str, Any] | None = None

        try:
            for iteration in range(1, max(1, REACT_MAX_ITERATIONS) + 1):
                prompt = json.dumps(
                    {
                        'protocol': 'ReAct chat',
                        'available_tools': get_registry_for_prompt(),
                        'observations_so_far': observations,
                        'question': question,
                        'conversation_history': incident_bundle.get('war_room_session_history', []),
                        'incident': bundle.get('incident', {}),
                        'alerts': bundle.get('alerts', []),
                        'timeline': bundle.get('timeline', [])[-20:],
                        'iteration': iteration,
                        'max_iterations': REACT_MAX_ITERATIONS,
                        'required_response_json': {
                            'thought': 'brief reasoning summary',
                            'action': {'name': 'tool name from available_tools', 'input': 'optional object'},
                            'final': {'answer': 'operator-facing markdown answer', 'confidence': 'low|medium|high', 'next_actions': ['string']},
                        },
                        'rules': [
                            'You are Cortex Supervisor. You are autonomous. Choose tools only when needed.',
                            'If conversation_history is present, use it to maintain context across questions.',
                            'If you already have enough context, skip tools and return final immediately.',
                            'Use at most one tool per iteration.',
                            'Return JSON only.',
                        ],
                    },
                    default=str,
                )
                response = await run_llm(
                    settings['provider'],
                    settings['model'],
                    [
                        {'role': 'system', 'content': get_agent_system_prompt('supervisor')},
                        {'role': 'user', 'content': prompt},
                    ],
                    temperature=0.1,
                    max_tokens=800,
                )
                if response.get('trace'):
                    llm_traces.append(response['trace'])
                provider = response.get('provider')
                model = response.get('model')
                parsed = self._parse_react_step(response['content'])
                action = parsed.get('action') if isinstance(parsed.get('action'), dict) else None
                thought = str(parsed.get('thought') or '')
                if action:
                    observation = await self._run_action(incident_bundle, action)
                    observations.append(observation)
                    step = {'kind': 'chat', 'iteration': iteration, 'thought': thought, 'action': action, 'observation': observation}
                    react_trace.append(step)
                    await self.memory.append(incident_id, step)
                    continue

                final = parsed.get('final') if isinstance(parsed.get('final'), dict) else parsed
                answer = str(final.get('answer') or answer)
                confidence = str(final.get('confidence') or confidence).lower()
                next_actions = final.get('next_actions') if isinstance(final.get('next_actions'), list) else []
                break
            llm_trace = {'status': 'ok', 'iterations': len(react_trace), 'calls': llm_traces}
        except Exception as exc:  # noqa: BLE001
            logger.warning('supervisor_chat_llm_fallback_used', extra={'provider': settings.get('provider'), 'model': settings.get('model'), 'error_type': type(exc).__name__})
            answer = (
                'Supervisor could not complete final LLM synthesis. '
                'Review the agent summary below and continue triage from collected context.'
            )
            confidence = 'low'
            next_actions = [
                'Confirm LLM provider credentials/billing and retry chat.',
                'Use observability and repo evidence panels to continue triage.',
            ]
            llm_trace = {'status': 'fallback', 'error': type(exc).__name__, 'provider': settings.get('provider'), 'model': settings.get('model')}
            provider = settings.get('provider')
            model = settings.get('model')

        agent_summary = {'supervisor-agent': 'Selected tools from the registry and synthesized available evidence into an operator-facing answer.'}
        for observation in observations:
            source = str(observation.get('source') or observation.get('tool') or 'unknown')
            agent_summary[source] = self._summarize_observation(observation)
        agent_summary.setdefault('history-agent', 'Provided incident, alert, and timeline context used by Supervisor.')
        final_step = {
            'kind': 'chat',
            'iteration': len(react_trace) + 1,
            'thought': 'Provide final operator response from collected evidence.',
            'final': {'answer': answer, 'confidence': confidence, 'next_actions': next_actions},
        }
        react_trace.append(final_step)
        await self.memory.append(incident_id, final_step)
        return {
            'incident_id': incident_id,
            'answer': answer,
            'confidence': confidence,
            'next_actions': next_actions,
            'agent_summary': agent_summary,
            'trace': react_trace,
            'llm_trace': llm_trace,
            'provider': provider,
            'model': model,
        }

    async def build_decision(self, incident_bundle: dict, settings: dict, reasoning_mode: str = 'balanced') -> dict:
        fallback = self.build_fallback_decision(incident_bundle, settings, reasoning_mode=reasoning_mode)
        incident_id = self._incident_id(incident_bundle)
        react_trace: list[dict[str, Any]] = []
        llm_traces: list[dict[str, Any]] = []
        try:
            bundle = _sanitize_bundle(normalize_incident_bundle(incident_bundle))
            rag_query = json.dumps({'incident': bundle.get('incident'), 'alerts': bundle.get('alerts', [])[:3]}, default=str)
            async with get_session_factory()() as rag_session:
                similar_past_incidents = await self.rag.retrieve_similar_incidents(
                    rag_session,
                    query_text=rag_query,
                    incident_id=incident_id,
                    limit=5,
                )
            observations: list[dict[str, Any]] = []
            response: dict[str, Any] = {}
            final_decision: dict[str, Any] | None = None
            for iteration in range(1, max(1, REACT_MAX_ITERATIONS) + 1):
                prompt = json.dumps(
                    {
                        'protocol': 'ReAct',
                        'available_tools': get_registry_for_prompt(),
                        'observations_so_far': observations,
                        'required_response_json': {
                            'thought': 'brief reasoning summary',
                            'action': {'name': 'tool name from available_tools', 'input': 'optional object'},
                            'final': {
                                'root_cause': 'string',
                                'confidence': 0.0,
                                'recommended_actions': [{'priority': 1, 'action': 'string'}],
                                'next_state': 'open|investigating|mitigating|resolved|closed',
                                'reasoning_trace': 'short trace',
                                'needs_human': False,
                                'human_request': 'string when human review is needed',
                            },
                        },
                        'rules': [
                            'You are Cortex Supervisor. You are autonomous. Choose tools only when needed.',
                            'If you already have enough context, skip tools and return final immediately.',
                            'Use at most one tool per iteration.',
                            'If confidence < 0.6 after collecting evidence, set needs_human=true in final.',
                            'Return JSON only.',
                        ],
                        'iteration': iteration,
                        'max_iterations': REACT_MAX_ITERATIONS,
                        'reasoning_mode': reasoning_mode,
                        'incident': bundle.get('incident', {}),
                        'alerts': bundle.get('alerts', []),
                        'timeline': bundle.get('timeline', []),
                        'similar_incidents': bundle.get('similar_incidents', []),
                        'similar_past_incidents': similar_past_incidents,
                        'fallback': fallback,
                        'request': 'Analyze the incident and recommend the next safe lifecycle state.',
                    },
                    default=str,
                )
                response = await run_llm(
                    settings['provider'],
                    settings['model'],
                    [
                        {'role': 'system', 'content': get_agent_system_prompt('supervisor') + '\n\nSimilar past incidents from long-term memory:\n' + json.dumps(similar_past_incidents, default=str)},
                        {'role': 'user', 'content': prompt},
                    ],
                    temperature=0.1,
                    max_tokens=700,
                )
                if response.get('trace'):
                    llm_traces.append(response['trace'])
                step = self._parse_react_step(response['content'])
                action = step.get('action') if isinstance(step.get('action'), dict) else None
                thought = str(step.get('thought') or '')
                observation = None
                if action:
                    observation = await self._run_action(incident_bundle, action)
                    observations.append(observation)
                    await self.memory.append(
                        incident_id,
                        {'iteration': iteration, 'thought': thought, 'action': action, 'observation': observation},
                    )
                    react_trace.append({'iteration': iteration, 'thought': thought, 'action': action, 'observation': observation})
                    continue

                final_decision = self._coerce_final_decision(step, fallback)
                react_trace.append({'iteration': iteration, 'thought': thought, 'action': action, 'final': final_decision})
                await self.memory.append(incident_id, {'iteration': iteration, 'thought': thought, 'final': final_decision})
                break

            if final_decision is None:
                observation_text = '; '.join(str(item.get('summary', '')) for item in observations if isinstance(item, dict))
                final_decision = fallback | {
                    'reasoning_trace': f"{fallback['reasoning_trace']} | react_max_iterations_reached | observations={observation_text}".strip(' |'),
                }

            return {
                **final_decision,
                'provider': response.get('provider', settings.get('provider')),
                'model': response.get('model', settings.get('model')),
                'context_enrichment': fallback['context_enrichment'],
                'llm_trace': {'status': 'ok', 'iterations': len(react_trace), 'calls': llm_traces},
                'react_trace': react_trace,
                'memory_key': incident_id,
                'similar_past_incidents': similar_past_incidents,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning('supervisor_llm_fallback_used', extra={'provider': settings.get('provider'), 'model': settings.get('model'), 'error_type': type(exc).__name__})
            fallback['llm_trace'] = {'provider': settings.get('provider'), 'model': settings.get('model'), 'status': 'fallback', 'error': type(exc).__name__}
            fallback['react_trace'] = react_trace
            fallback['memory_key'] = incident_id
            fallback.setdefault('similar_past_incidents', [])
            return fallback
