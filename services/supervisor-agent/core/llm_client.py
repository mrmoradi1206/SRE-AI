import json

from ai_client import AICompletionRequest, AIMessage, resolve_client_for_agent
from aiops_shared.schemas import AISettingsOut


class CMDBEnricher:
    def enrich(self, incident_bundle: dict) -> dict:
        incident = incident_bundle.get('incident', {})
        return {
            'service_tier': 'gold' if incident.get('severity') in {'critical', 'high'} else 'silver',
            'owning_team': 'platform-sre',
            'runbook_url': 'https://runbooks.example.local/sre-ai/incident-response',
        }


class SupervisorAdvisor:
    def __init__(self) -> None:
        self.cmdb = CMDBEnricher()

    def build_fallback_decision(self, incident_bundle: dict, settings: AISettingsOut, reasoning_mode: str = 'balanced') -> dict:
        alerts = incident_bundle.get('alerts', [])
        incident = incident_bundle['incident']
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
            'provider': settings.provider,
            'model': settings.model,
            'context_enrichment': enrichment,
        }

    async def build_decision(self, incident_bundle: dict, settings: AISettingsOut, reasoning_mode: str = 'balanced') -> dict:
        fallback = self.build_fallback_decision(incident_bundle, settings, reasoning_mode=reasoning_mode)
        try:
            client = resolve_client_for_agent('supervisor-agent', settings=settings)
            prompt = json.dumps(
                {
                    'reasoning_mode': reasoning_mode,
                    'incident': incident_bundle.get('incident', {}),
                    'alerts': incident_bundle.get('alerts', [])[:20],
                    'timeline': incident_bundle.get('timeline', [])[:40],
                    'fallback': fallback,
                },
                default=str,
            )
            response = await client.complete(
                AICompletionRequest(
                    model=settings.model,
                    messages=[
                        AIMessage(
                            role='system',
                            content=(
                                'You are an SRE supervisor. Respond only as JSON with keys '
                                'root_cause, confidence, recommended_actions, next_state, reasoning_trace.'
                            ),
                        ),
                        AIMessage(role='user', content=prompt),
                    ],
                    max_tokens=500,
                )
            )
            decision = json.loads(response.content)
            return {
                'root_cause': decision.get('root_cause', fallback['root_cause']),
                'confidence': float(decision.get('confidence', fallback['confidence'])),
                'recommended_actions': decision.get('recommended_actions', fallback['recommended_actions']),
                'next_state': decision.get('next_state', fallback['next_state']),
                'reasoning_trace': decision.get('reasoning_trace', fallback['reasoning_trace']),
                'provider': response.provider,
                'model': response.model,
                'context_enrichment': fallback['context_enrichment'],
                'raw_completion': response.raw_response,
            }
        except Exception:
            return fallback
