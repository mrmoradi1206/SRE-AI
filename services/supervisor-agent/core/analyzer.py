from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.event_store import append_event
from aiops_shared.projector import apply_event_to_projection
from aiops_shared.schemas import AISettingsOut
from aiops_shared.utils import utcnow
from aiops_shared.models import AISettings, Incident, IncidentStatus

from .config import AI_API_KEY, AI_EXTRA_CONFIG, AI_MODEL, AI_PROVIDER
from .llm_client import SupervisorAdvisor
from .fsm import apply_transition


class AnalysisService:
    def __init__(self) -> None:
        self.advisor = SupervisorAdvisor()

    async def current_settings(self, session: AsyncSession) -> AISettingsOut:
        settings = (await session.execute(select(AISettings).order_by(AISettings.id.asc()).limit(1))).scalar_one_or_none()
        if settings is None:
            return AISettingsOut(id=None, provider=AI_PROVIDER, model=AI_MODEL, api_key=AI_API_KEY or None, extra_config={'raw': AI_EXTRA_CONFIG}, version=1)
        return AISettingsOut(id=settings.id, provider=settings.provider, model=settings.model, api_key=settings.api_key, extra_config=settings.extra_config, version=settings.version)

    async def analyze(self, session: AsyncSession, incident: Incident, incident_bundle: dict, *, reasoning_mode: str, actor: str, metadata: dict, correlation_id, idempotency_key: str | None) -> dict:
        settings = await self.current_settings(session)
        decision = await self.advisor.build_decision(incident_bundle, settings, reasoning_mode=reasoning_mode)

        next_state = decision['next_state']
        if next_state != incident.status.value:
            transition = apply_transition(incident, IncidentStatus(next_state), actor, decision['root_cause'], utcnow())
            if transition.changed:
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
                'decision': next_state,
                'root_cause': decision['root_cause'],
                'recommended_actions': decision['recommended_actions'],
            },
            metadata=metadata | {
                'reasoning_output': decision,
                'supervisor_output': decision,
                'actor': actor,
            },
        )
        return decision | {'event_id': str(supervisor_event.event_id)}
