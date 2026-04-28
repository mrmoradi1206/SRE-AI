from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.event_store import append_event
from aiops_shared.fingerprint import compute_dedup_key, compute_fingerprint, compute_grouping_key, normalize_severity
from aiops_shared.metrics import AGENT_ACTIONS, QUEUE_DEPTH
from aiops_shared.models import Alert, AlertEvent, DeadLetterQueue, DeadLetterStatus, EventQueue, Incident, IncidentSeverity, IncidentStatus, QueueStatus
from aiops_shared.projector import apply_event_to_projection
from aiops_shared.queue import BackpressureExceededError, enqueue_job
from aiops_shared.schemas import AlertIn
from aiops_shared.utils import choose_higher_severity, utcnow

from .config import DEFAULT_ALERT_CONTEXT_HOURS, DEFAULT_SLA_HOURS, REOPEN_STALE_AFTER_HOURS

ACTIVE_INCIDENTS = [IncidentStatus.OPEN, IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATING]


def _payload_received_at(payload: AlertIn) -> datetime:
    candidate = (
        payload.payload.get('received_at')
        or payload.payload.get('startsAt')
        or payload.payload.get('starts_at')
        or payload.payload.get('timestamp')
        or payload.metadata.get('received_at')
    )
    if isinstance(candidate, str):
        try:
            return datetime.fromisoformat(candidate.replace('Z', '+00:00'))
        except ValueError:
            return utcnow()
    return candidate if isinstance(candidate, datetime) else utcnow()


def should_reopen_incident(incident: Incident, *, observed_at: datetime, stale_after_hours: int) -> bool:
    if incident.status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
        return False
    if incident.resolved_at is None:
        return False
    if observed_at <= incident.resolved_at:
        return False
    return observed_at <= incident.resolved_at + timedelta(hours=stale_after_hours)


async def ingest_alert(
    session: AsyncSession,
    payload: AlertIn,
    *,
    correlation_id: UUID | None,
    idempotency_key: str | None,
    request_metadata: dict,
) -> Alert:
    fingerprint = compute_fingerprint(payload.payload)
    grouping_key = payload.grouping_key or compute_grouping_key(payload.payload)
    dedup_key = payload.dedup_key or compute_dedup_key(payload.payload)
    severity = normalize_severity(payload.payload, fallback=payload.severity or 'unknown')
    event_key = payload.event_key or f'{fingerprint}-{uuid4()}'
    summary = payload.summary or payload.payload.get('summary') or payload.payload.get('message')
    source = payload.source or payload.payload.get('source')
    now = _payload_received_at(payload)

    incident = (
        await session.execute(
            select(Incident)
            .where(Incident.grouping_key == grouping_key)
            .order_by(desc(Incident.last_seen_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    opened_event = None
    is_reopen = incident is not None and should_reopen_incident(incident, observed_at=now, stale_after_hours=REOPEN_STALE_AFTER_HOURS)
    if incident is None or is_reopen:
        incident = Incident(
            fingerprint=fingerprint,
            grouping_key=grouping_key,
            dedup_key=dedup_key,
            summary=summary,
            severity=IncidentSeverity(severity),
            status=IncidentStatus.OPEN,
            first_seen_at=now,
            last_seen_at=now,
            sla_deadline=now + timedelta(hours=DEFAULT_SLA_HOURS),
        )
        session.add(incident)
        await session.flush()
        event_type = 'history.incident_reopened' if is_reopen else 'history.incident_opened'
        opened_event = await append_event(
            session,
            stream_id=incident.id,
            event_type=event_type,
            actor='history-agent',
            correlation_id=correlation_id,
            payload={
                'fingerprint': fingerprint,
                'grouping_key': grouping_key,
                'dedup_key': dedup_key,
                'summary': summary,
                'severity': severity,
                'initial_state': IncidentStatus.OPEN.value,
                'sla_deadline': incident.sla_deadline.isoformat() if incident.sla_deadline else None,
            },
            metadata=request_metadata,
        )
        await apply_event_to_projection(session, incident, opened_event)
    else:
        incident.last_seen_at = now
        incident.summary = summary or incident.summary
        incident.fingerprint = fingerprint
        incident.dedup_key = dedup_key
        incident.severity = IncidentSeverity(choose_higher_severity(incident.severity.value, severity))
        incident.source_count += 1

    alert = Alert(
        incident_id=incident.id,
        fingerprint=fingerprint,
        grouping_key=grouping_key,
        dedup_key=dedup_key,
        event_key=event_key,
        source=source,
        severity=severity,
        correlation_id=correlation_id,
        payload=payload.payload,
    )
    session.add(alert)
    await session.flush()
    session.add(
        AlertEvent(
            alert_id=alert.id,
            version=1,
            event_type='ingested',
            payload=payload.payload,
        )
    )

    attached_event = await append_event(
        session,
        stream_id=incident.id,
        event_type='history.alert_attached',
        actor='history-agent',
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        causation_id=opened_event.event_id if opened_event else None,
        payload={
            'alert_id': str(alert.id),
            'event_key': alert.event_key,
            'fingerprint': fingerprint,
            'grouping_key': grouping_key,
            'dedup_key': dedup_key,
            'severity': severity,
            'summary': summary,
        },
        metadata=request_metadata,
    )
    await apply_event_to_projection(session, incident, attached_event)

    try:
        await enqueue_job(
            session,
            topic='supervisor.analyze',
            payload={'incident_id': str(incident.id), 'reasoning_mode': 'balanced'},
            stream_id=incident.id,
            correlation_id=correlation_id,
            idempotency_key=f'analyze:{incident.id}:{attached_event.sequence_number}',
        )
    except BackpressureExceededError:
        pass
    AGENT_ACTIONS.labels('history-agent', 'alert_ingested').inc()
    pending = await session.scalar(select(func.count()).select_from(EventQueue).where(EventQueue.status.in_([QueueStatus.PENDING, QueueStatus.RETRYING])))
    QUEUE_DEPTH.labels('supervisor.analyze').set(int(pending or 0))
    return alert


async def ingest_alert_batch(
    session: AsyncSession,
    alerts: list[AlertIn],
    *,
    correlation_id: UUID | None,
    idempotency_key: str | None,
    request_metadata: dict,
) -> list[Alert]:
    results: list[Alert] = []
    for index, alert in enumerate(alerts):
        derived_idempotency = f'{idempotency_key}:{index}' if idempotency_key else None
        results.append(
            await ingest_alert(
                session,
                alert,
                correlation_id=correlation_id or alert.correlation_id,
                idempotency_key=derived_idempotency,
                request_metadata=request_metadata | alert.metadata,
            )
        )
    return results


async def recent_alerts_summary(session: AsyncSession, *, hours: int = DEFAULT_ALERT_CONTEXT_HOURS, limit: int = 20) -> list[Alert]:
    cutoff = utcnow() - timedelta(hours=hours)
    query = (
        select(Alert)
        .where(Alert.created_at >= cutoff)
        .order_by(Alert.created_at.desc())
        .limit(limit)
    )
    return (await session.execute(query)).scalars().all()


async def dashboard_counts(session: AsyncSession) -> dict:
    since = utcnow().replace(microsecond=0) - timedelta(hours=24)
    open_count = await session.scalar(select(func.count()).select_from(Incident).where(Incident.status == IncidentStatus.OPEN))
    investigating_count = await session.scalar(select(func.count()).select_from(Incident).where(Incident.status == IncidentStatus.INVESTIGATING))
    mitigating_count = await session.scalar(select(func.count()).select_from(Incident).where(Incident.status == IncidentStatus.MITIGATING))
    alerts_last_24h = await session.scalar(select(func.count()).select_from(Alert).where(Alert.created_at >= since))
    resolved_last_24h = await session.scalar(
        select(func.count()).select_from(Incident).where(Incident.status == IncidentStatus.RESOLVED, Incident.resolved_at >= since)
    )
    dlq_pending_count = await session.scalar(
        select(func.count()).select_from(DeadLetterQueue).where(DeadLetterQueue.status.in_([DeadLetterStatus.PENDING, DeadLetterStatus.RETRYING]))
    )
    queue_pending_count = await session.scalar(
        select(func.count()).select_from(EventQueue).where(EventQueue.status.in_([QueueStatus.PENDING, QueueStatus.RETRYING]))
    )
    return {
        'open_incidents_count': int(open_count or 0),
        'investigating_incidents_count': int(investigating_count or 0),
        'mitigating_incidents_count': int(mitigating_count or 0),
        'alerts_last_24h': int(alerts_last_24h or 0),
        'resolved_last_24h': int(resolved_last_24h or 0),
        'dlq_pending_count': int(dlq_pending_count or 0),
        'queue_pending_count': int(queue_pending_count or 0),
    }


def translate_integrity_error(exc: IntegrityError) -> str:
    raw = str(exc.orig)
    if 'event_key' in raw:
        return 'duplicate event_key'
    if 'idempotency_key' in raw:
        return 'duplicate idempotency_key'
    return 'failed to ingest alert'
