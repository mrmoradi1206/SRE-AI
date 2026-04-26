from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Alert, Incident, IncidentEvent
from .schemas import AlertOut, EventEnvelopeOut


async def load_incident_bundle(session: AsyncSession, incident_id: UUID | str, *, alert_limit: int = 100) -> dict:
    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
    if incident is None:
        raise LookupError('incident not found')
    alerts = (
        await session.execute(
            select(Alert).where(Alert.incident_id == incident.id).order_by(Alert.created_at.desc()).limit(alert_limit)
        )
    ).scalars().all()
    timeline = (
        await session.execute(
            select(IncidentEvent).where(IncidentEvent.stream_id == incident.id).order_by(IncidentEvent.sequence_number.asc())
        )
    ).scalars().all()
    return {
        'incident': {
            'id': str(incident.id),
            'fingerprint': incident.fingerprint,
            'grouping_key': incident.grouping_key,
            'dedup_key': incident.dedup_key,
            'summary': incident.summary,
            'severity': incident.severity.value,
            'status': incident.status.value,
            'first_seen_at': incident.first_seen_at.isoformat(),
            'last_seen_at': incident.last_seen_at.isoformat(),
            'acknowledged_at': incident.acknowledged_at.isoformat() if incident.acknowledged_at else None,
            'acknowledged_by': incident.acknowledged_by,
            'mitigated_at': incident.mitigated_at.isoformat() if incident.mitigated_at else None,
            'mitigated_by': incident.mitigated_by,
            'resolved_at': incident.resolved_at.isoformat() if incident.resolved_at else None,
            'resolved_by': incident.resolved_by,
            'closed_at': incident.closed_at.isoformat() if incident.closed_at else None,
            'closed_by': incident.closed_by,
            'escalated_to': incident.escalated_to,
            'sla_deadline': incident.sla_deadline.isoformat() if incident.sla_deadline else None,
            'sla_violated': incident.sla_violated,
            'mttr_seconds': incident.mttr_seconds,
            'source_count': incident.source_count,
            'projection_version': incident.projection_version,
            'created_at': incident.created_at.isoformat(),
            'updated_at': incident.updated_at.isoformat(),
        },
        'alerts': [AlertOut.model_validate(alert).model_dump(mode='json') for alert in alerts],
        'timeline': [EventEnvelopeOut.model_validate(event).model_dump(mode='json') for event in timeline],
    }
