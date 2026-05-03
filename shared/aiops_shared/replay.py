from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Incident, IncidentEvent, IncidentSeverity, IncidentStatus
from .utils import calculate_mttr_seconds


@dataclass
class IncidentProjectionState:
    incident_id: UUID
    fingerprint: str = ''
    grouping_key: str = ''
    dedup_key: str = ''
    summary: str | None = None
    severity: str = IncidentSeverity.UNKNOWN.value
    status: str = IncidentStatus.OPEN.value
    first_seen_at: Any = None
    last_seen_at: Any = None
    acknowledged_at: Any = None
    acknowledged_by: str | None = None
    resolved_by: str | None = None
    escalated_to: str | None = None
    mitigated_at: Any = None
    mitigated_by: str | None = None
    resolved_at: Any = None
    closed_at: Any = None
    closed_by: str | None = None
    sla_deadline: Any = None
    sla_violated: bool = False
    mttr_seconds: int | None = None
    source_count: int = 0
    projection_version: int = 0

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_ts(value: Any, default: datetime | None) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return default
    return value if value is not None else default


def apply_event_to_state(state: IncidentProjectionState, event: IncidentEvent) -> IncidentProjectionState:
    payload = event.payload or {}
    metadata = event.event_metadata or {}
    state.projection_version = event.sequence_number

    if event.event_type == 'history.incident_opened':
        state.fingerprint = payload.get('fingerprint', state.fingerprint)
        state.grouping_key = payload.get('grouping_key', state.grouping_key)
        state.dedup_key = payload.get('dedup_key', state.dedup_key)
        state.summary = payload.get('summary', state.summary)
        state.severity = payload.get('severity', state.severity)
        state.status = payload.get('initial_state', IncidentStatus.OPEN.value)
        state.first_seen_at = event.created_at
        state.last_seen_at = event.created_at
        state.sla_deadline = _coerce_ts(payload.get('sla_deadline'), state.sla_deadline)
        state.source_count = max(state.source_count, 1)
    elif event.event_type == 'history.alert_attached':
        state.fingerprint = payload.get('fingerprint', state.fingerprint)
        state.grouping_key = payload.get('grouping_key', state.grouping_key)
        state.dedup_key = payload.get('dedup_key', state.dedup_key)
        state.summary = payload.get('summary', state.summary)
        state.severity = payload.get('severity', state.severity)
        state.last_seen_at = event.created_at
        state.source_count += 1
    elif event.event_type == 'supervisor.status_changed':
        state.status = payload.get('to', state.status)
        actor = metadata.get('actor') or event.actor
        if state.status == IncidentStatus.INVESTIGATING.value:
            state.acknowledged_at = event.created_at
            state.acknowledged_by = actor
        elif state.status == IncidentStatus.MITIGATING.value:
            state.mitigated_at = event.created_at
            state.mitigated_by = actor
        elif state.status == IncidentStatus.RESOLVED.value:
            state.resolved_at = event.created_at
            state.resolved_by = actor
            state.mttr_seconds = calculate_mttr_seconds(state.resolved_at, state.first_seen_at)
            state.sla_violated = bool(state.sla_deadline and state.resolved_at and state.resolved_at > state.sla_deadline)
        elif state.status == IncidentStatus.CLOSED.value:
            state.closed_at = event.created_at
            state.closed_by = actor
    elif event.event_type == 'history.incident_resolved':
        actor = metadata.get('actor') or event.actor
        state.status = IncidentStatus.RESOLVED.value
        state.resolved_at = event.created_at
        state.resolved_by = actor
        state.mttr_seconds = calculate_mttr_seconds(state.resolved_at, state.first_seen_at)
        state.sla_violated = bool(state.sla_deadline and state.resolved_at and state.resolved_at > state.sla_deadline)
    elif event.event_type in {'supervisor.supervisor_action', 'supervisor.action_recorded'}:
        supervisor_output = metadata.get('supervisor_output') or metadata.get('reasoning_output') or {}
        state.escalated_to = supervisor_output.get('next_state') or payload.get('decision') or state.escalated_to
    return state


async def replay_incident_stream(session: AsyncSession, stream_id: UUID) -> tuple[IncidentProjectionState, list[IncidentEvent]]:
    events = (
        await session.execute(
            select(IncidentEvent).where(IncidentEvent.stream_id == stream_id).order_by(IncidentEvent.sequence_number.asc())
        )
    ).scalars().all()
    state = IncidentProjectionState(incident_id=stream_id)
    for event in events:
        state = apply_event_to_state(state, event)
    return state, events


async def rebuild_incident_projection(session: AsyncSession, incident: Incident) -> Incident:
    state, _ = await replay_incident_stream(session, incident.id)
    incident.fingerprint = state.fingerprint
    incident.grouping_key = state.grouping_key
    incident.dedup_key = state.dedup_key
    incident.summary = state.summary
    incident.severity = IncidentSeverity(state.severity)
    incident.status = IncidentStatus(state.status)
    incident.first_seen_at = state.first_seen_at
    incident.last_seen_at = state.last_seen_at
    incident.acknowledged_at = state.acknowledged_at
    incident.acknowledged_by = state.acknowledged_by
    incident.resolved_by = state.resolved_by
    incident.escalated_to = state.escalated_to
    incident.mitigated_at = state.mitigated_at
    incident.mitigated_by = state.mitigated_by
    incident.resolved_at = state.resolved_at
    incident.closed_at = state.closed_at
    incident.closed_by = state.closed_by
    incident.sla_deadline = state.sla_deadline
    incident.sla_violated = state.sla_violated
    incident.mttr_seconds = state.mttr_seconds
    incident.source_count = state.source_count
    incident.projection_version = state.projection_version
    return incident
