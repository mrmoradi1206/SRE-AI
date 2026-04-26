from sqlalchemy.ext.asyncio import AsyncSession

from .models import Incident, IncidentSeverity, IncidentStatus
from .replay import IncidentProjectionState, apply_event_to_state


def _state_from_incident(incident: Incident) -> IncidentProjectionState:
    return IncidentProjectionState(
        incident_id=incident.id,
        fingerprint=incident.fingerprint,
        grouping_key=incident.grouping_key,
        dedup_key=incident.dedup_key,
        summary=incident.summary,
        severity=incident.severity.value if hasattr(incident.severity, 'value') else str(incident.severity),
        status=incident.status.value if hasattr(incident.status, 'value') else str(incident.status),
        first_seen_at=incident.first_seen_at,
        last_seen_at=incident.last_seen_at,
        acknowledged_at=incident.acknowledged_at,
        acknowledged_by=incident.acknowledged_by,
        resolved_by=incident.resolved_by,
        escalated_to=incident.escalated_to,
        mitigated_at=incident.mitigated_at,
        mitigated_by=incident.mitigated_by,
        resolved_at=incident.resolved_at,
        closed_at=incident.closed_at,
        closed_by=incident.closed_by,
        sla_deadline=incident.sla_deadline,
        sla_violated=incident.sla_violated,
        mttr_seconds=incident.mttr_seconds,
        source_count=incident.source_count,
        projection_version=incident.projection_version,
    )


async def apply_event_to_projection(session: AsyncSession, incident: Incident, event) -> Incident:
    state = apply_event_to_state(_state_from_incident(incident), event)
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
    await session.flush()
    return incident
