import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.fingerprint import generate_fingerprint
from aiops_shared.models import Alert, Incident, IncidentAlert, TimelineEntry
from aiops_shared.schemas import AlertPayload

logger = logging.getLogger(__name__)


def _incident_title(labels: dict) -> str:
    return f"{labels.get('alertname', 'Alert')} on {labels.get('instance', 'unknown')}"


async def create_timeline_entry(
    session: AsyncSession,
    incident_id: UUID,
    agent_name: str,
    action: str,
    status: str,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    session.add(
        TimelineEntry(
            incident_id=incident_id,
            agent_name=agent_name,
            action=action,
            status=status,
            details=details,
            error_message=error_message,
        )
    )


async def store_alert(session: AsyncSession, alert: AlertPayload) -> tuple[Alert, Incident, bool]:
    fingerprint = generate_fingerprint(alert.labels)
    status = alert.status
    severity = alert.labels.get('severity', 'unknown')
    now = datetime.now(timezone.utc)

    stmt = insert(Alert).values(
        fingerprint=fingerprint,
        raw_payload=alert.model_dump(mode='json'),
        labels=alert.labels,
        annotations=alert.annotations or {},
        severity=severity,
        status=status,
        received_at=now,
        resolved_at=alert.endsAt if status == 'resolved' else None,
    ).on_conflict_do_update(
        index_elements=[Alert.fingerprint],
        set_={
            'raw_payload': alert.model_dump(mode='json'),
            'labels': alert.labels,
            'annotations': alert.annotations or {},
            'severity': severity,
            'status': status,
            'received_at': now,
            'resolved_at': alert.endsAt if status == 'resolved' else None,
        },
    ).returning(Alert)
    stored_alert = (await session.execute(stmt)).scalar_one()

    incident_result = await session.execute(select(Incident).where(Incident.fingerprint == fingerprint))
    incident = incident_result.scalar_one_or_none()
    is_new = incident is None
    if incident is None:
        incident = Incident(
            fingerprint=fingerprint,
            title=_incident_title(alert.labels),
            severity=severity,
            status='open' if status != 'resolved' else 'resolved',
            resolved_at=alert.endsAt if status == 'resolved' else None,
        )
        session.add(incident)
        await session.flush()
    else:
        incident.severity = severity
        if status == 'resolved':
            incident.status = 'resolved'
            incident.resolved_at = alert.endsAt or now
        elif incident.status == 'resolved':
            incident.status = 'open'
            incident.resolved_at = None

    link_stmt = insert(IncidentAlert).values(incident_id=incident.id, alert_id=stored_alert.id).on_conflict_do_nothing()
    await session.execute(link_stmt)
    await create_timeline_entry(
        session,
        incident.id,
        'history-agent',
        'alert_ingested',
        'success',
        {'fingerprint': fingerprint, 'status': status},
    )
    await session.commit()
    await session.refresh(incident)
    return stored_alert, incident, is_new


async def fetch_incident_context(session: AsyncSession, fingerprint: str, hours: int) -> dict | None:
    incident = (await session.execute(select(Incident).where(Incident.fingerprint == fingerprint))).scalar_one_or_none()
    if incident is None:
        return None

    alerts = (await session.execute(
        select(Alert).where(Alert.fingerprint == fingerprint).order_by(Alert.received_at.desc())
    )).scalars().all()
    timeline = (await session.execute(
        select(TimelineEntry).where(TimelineEntry.incident_id == incident.id).order_by(TimelineEntry.created_at.desc())
    )).scalars().all()

    def dump_alert(row: Alert) -> dict:
        return {
            'id': str(row.id),
            'fingerprint': row.fingerprint,
            'labels': row.labels,
            'annotations': row.annotations,
            'severity': row.severity,
            'status': row.status,
            'received_at': row.received_at.isoformat() if row.received_at else None,
            'resolved_at': row.resolved_at.isoformat() if row.resolved_at else None,
        }

    return {
        'incident': {
            'id': str(incident.id),
            'fingerprint': incident.fingerprint,
            'title': incident.title,
            'severity': incident.severity,
            'status': incident.status,
            'root_cause': incident.root_cause,
            'business_impact': incident.business_impact,
            'diagnosis': incident.diagnosis,
            'recommendations': incident.recommendations,
            'created_at': incident.created_at.isoformat() if incident.created_at else None,
            'updated_at': incident.updated_at.isoformat() if incident.updated_at else None,
        },
        'current_alert': dump_alert(alerts[0]) if alerts else None,
        'historical_alerts': [dump_alert(item) for item in alerts[:hours]] if alerts else [],
        'timeline': [
            {
                'agent_name': item.agent_name,
                'action': item.action,
                'status': item.status,
                'details': item.details,
                'error_message': item.error_message,
                'created_at': item.created_at.isoformat() if item.created_at else None,
            }
            for item in timeline
        ],
    }


async def fetch_incidents(session: AsyncSession) -> list[dict]:
    incidents = (await session.execute(select(Incident).order_by(Incident.created_at.desc()))).scalars().all()
    return [
        {
            'id': str(item.id),
            'fingerprint': item.fingerprint,
            'title': item.title,
            'severity': item.severity,
            'status': item.status,
            'created_at': item.created_at.isoformat() if item.created_at else None,
            'updated_at': item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in incidents
    ]


async def fetch_timeline(session: AsyncSession, incident_id: UUID) -> list[dict]:
    entries = (await session.execute(
        select(TimelineEntry).where(TimelineEntry.incident_id == incident_id).order_by(TimelineEntry.created_at.desc())
    )).scalars().all()
    return [
        {
            'id': item.id,
            'agent_name': item.agent_name,
            'action': item.action,
            'status': item.status,
            'details': item.details,
            'error_message': item.error_message,
            'created_at': item.created_at.isoformat() if item.created_at else None,
        }
        for item in entries
    ]


async def update_incident_analysis(session: AsyncSession, incident_id: UUID, analysis: dict) -> None:
    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one()
    incident.root_cause = analysis.get('root_cause')
    incident.diagnosis = analysis.get('diagnosis')
    incident.business_impact = analysis.get('business_impact')
    incident.recommendations = analysis.get('recommendations', [])
    incident.analysis_confidence = analysis.get('confidence')
    incident.severity = analysis.get('severity', incident.severity)
    incident.status = 'analyzing'
    await create_timeline_entry(session, incident_id, 'supervisor-agent', 'analysis_saved', 'success', analysis)
    await session.commit()


async def update_incident_status(session: AsyncSession, incident_id: UUID, status: str) -> None:
    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one()
    incident.status = status
    await create_timeline_entry(session, incident_id, 'report-agent', 'incident_status_updated', 'success', {'status': status})
    await session.commit()
