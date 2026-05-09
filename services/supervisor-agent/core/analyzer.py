from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.event_store import append_event
from aiops_shared.fsm import InvalidIncidentTransitionError, can_transition
from aiops_shared.llm_config import get_agent_llm_config
from aiops_shared.models import Incident, IncidentStatus
from aiops_shared.projector import apply_event_to_projection
from aiops_shared.schemas import AISettingsOut, SupervisorDecisionOut
from aiops_shared.utils import utcnow

from .config import AI_MODEL, AI_PROVIDER
from .fsm import apply_transition
from .llm_client import SupervisorAdvisor


class AnalysisService:
    def __init__(self) -> None:
        self.advisor = SupervisorAdvisor()

    async def current_settings(self, session: AsyncSession | None = None) -> AISettingsOut:
        selection = get_agent_llm_config('supervisor')
        return AISettingsOut(id=None, provider=selection['provider'], model=selection['model'], api_key=None, extra_config={}, version=None)

    async def analyze(self, session: AsyncSession, incident: Incident, incident_bundle: dict, *, reasoning_mode: str, actor: str, metadata: dict, correlation_id, idempotency_key: str | None) -> dict:
        settings = get_agent_llm_config('supervisor')
        decision = await self.advisor.build_decision(incident_bundle, settings, reasoning_mode=reasoning_mode)
        decision['confidence'] = max(0.0, min(1.0, float(decision.get('confidence', 0.0))))
        if not isinstance(decision.get('recommended_actions'), list):
            decision['recommended_actions'] = []
        decision['recommended_actions'] = [
            item if isinstance(item, dict) else {'priority': idx + 1, 'action': str(item)}
            for idx, item in enumerate(decision['recommended_actions'])
        ]
        if not isinstance(decision.get('requested_context'), list):
            decision['requested_context'] = []
        if not isinstance(decision.get('react_trace'), list):
            decision['react_trace'] = []
        normalized = SupervisorDecisionOut(
            root_cause=str(decision.get('root_cause') or 'No root cause identified.'),
            confidence=decision['confidence'],
            recommended_actions=decision['recommended_actions'],
            next_state=str(decision.get('next_state') or incident.status.value),
            reasoning_trace=str(decision.get('reasoning_trace') or ''),
        )
        decision.update(normalized.model_dump())

        next_state = str(decision.get('next_state') or incident.status.value).lower()
        try:
            target_status = IncidentStatus(next_state)
        except ValueError:
            target_status = incident.status
            decision['next_state'] = incident.status.value
            decision['reasoning_trace'] = f"{decision.get('reasoning_trace', '')} | invalid_next_state={next_state}".strip(' |')

        if target_status != incident.status:
            if not can_transition(incident.status, target_status):
                decision['next_state'] = incident.status.value
                decision['reasoning_trace'] = f"{decision.get('reasoning_trace', '')} | blocked_transition={incident.status.value}->{target_status.value}".strip(' |')
            else:
                try:
                    transition = apply_transition(incident, target_status, actor, decision['root_cause'], utcnow())
                except InvalidIncidentTransitionError:
                    transition = None
                    decision['next_state'] = incident.status.value
                if transition and transition.changed:
                    status_event = await append_event(
                        session,
                        stream_id=incident.id,
                        event_type='supervisor.status_changed',
                        actor='supervisor',
                        correlation_id=correlation_id,
                        payload={'from': transition.from_status, 'to': transition.to_status, 'reason': transition.reason},
                        metadata=metadata | {'actor': actor},
                    )
                    await apply_event_to_projection(session, incident, status_event)

        supervisor_event = await append_event(
            session,
            stream_id=incident.id,
            event_type='supervisor.action_recorded',
            actor='supervisor',
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload={
                'decision': decision['next_state'],
                'root_cause': decision['root_cause'],
                'recommended_actions': decision['recommended_actions'],
                'requested_context': decision.get('requested_context', []),
                'react_trace': decision.get('react_trace', []),
            },
            metadata=metadata | {
                'reasoning_output': decision,
                'supervisor_output': decision,
                'actor': actor,
            },
        )
        return decision | {'event_id': str(supervisor_event.event_id)}

    async def answer_operator_question(self, incident_bundle: dict, question: str) -> dict:
        settings = get_agent_llm_config('supervisor')
        return await self.advisor.answer_question(incident_bundle, question, settings)
