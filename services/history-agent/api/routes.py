import hashlib
import hmac
import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_db
from aiops_shared.models import Alert, Incident, IncidentEvent
from aiops_shared.replay import replay_incident_stream
from aiops_shared.schemas import AlertBatchIn, AlertIn, AlertOut, DashboardStats, EventEnvelopeOut, IncidentListItem, IncidentOut, IncidentReplayOut
from aiops_shared.utils import clamp_page_size, health_payload

from core.config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SERVICE_NAME
from core.search import apply_incident_filters, build_incident_detail
from core.storage import dashboard_counts, ingest_alert, ingest_alert_batch, recent_alerts_summary, translate_integrity_error

router = APIRouter()


def _request_metadata(request: Request) -> dict:
    return {
        'request_id': getattr(request.state, 'request_id', None),
        'trace_id': getattr(request.state, 'trace_id', None),
        'correlation_id': getattr(request.state, 'correlation_id', None),
        'path': str(request.url.path),
        'method': request.method,
        'remote_addr': request.client.host if request.client else None,
    }


async def _verify_webhook_signature(request: Request) -> None:
    secret = os.getenv('ALERT_WEBHOOK_SECRET')
    if not secret:
        return
    provided = request.headers.get('X-SRE-AI-Signature') or request.headers.get('X-Hub-Signature-256')
    if not provided:
        raise HTTPException(status_code=401, detail='missing webhook signature')
    signature = provided.removeprefix('sha256=')
    expected = hmac.new(secret.encode('utf-8'), await request.body(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail='invalid webhook signature')


@router.get('/health')
async def health(session: AsyncSession = Depends(get_db)) -> dict:
    database = 'connected'
    try:
        await session.execute(text('SELECT 1'))
    except Exception:
        database = 'disconnected'
    return health_payload(SERVICE_NAME, database, readiness=database)


@router.get('/ready')
async def ready(session: AsyncSession = Depends(get_db)) -> dict:
    try:
        await session.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='database unavailable') from exc
    return health_payload(SERVICE_NAME, 'connected', readiness='ready')


@router.post('/alerts', status_code=201)
async def create_alert(
    alert_in: AlertBatchIn | AlertIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    session: AsyncSession = Depends(get_db),
) -> AlertOut | dict:
    await _verify_webhook_signature(request)
    try:
        async with session.begin():
            if isinstance(alert_in, AlertBatchIn):
                alerts = await ingest_alert_batch(
                    session,
                    alert_in.alerts,
                    correlation_id=None,
                    idempotency_key=idempotency_key,
                    request_metadata=_request_metadata(request),
                )
                for alert in alerts:
                    await session.refresh(alert)
                return {
                    'processed': len(alerts),
                    'created': len(alerts),
                    'updated': 0,
                    'duplicates': 0,
                    'incidents_created': len({str(alert.incident_id) for alert in alerts}),
                    'incident_ids': [str(alert.incident_id) for alert in alerts],
                    'results': [AlertOut.model_validate(alert).model_dump(mode='json') for alert in alerts],
                }

            correlation_id = alert_in.correlation_id
            alert = await ingest_alert(
                session,
                alert_in,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                request_metadata=_request_metadata(request) | alert_in.metadata,
            )
            await session.refresh(alert)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=translate_integrity_error(exc)) from exc
    return AlertOut.model_validate(alert)


@router.get('/incidents')
async def list_incidents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    status: str | None = None,
    fingerprint: str | None = None,
    query: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict:
    safe_page_size = clamp_page_size(page_size, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE)
    offset = (page - 1) * safe_page_size

    base_stmt = apply_incident_filters(select(Incident), status, fingerprint, created_from, created_to, query=query)
    total_stmt = apply_incident_filters(select(func.count()).select_from(Incident), status, fingerprint, created_from, created_to, query=query)
    total = int((await session.scalar(total_stmt)) or 0)
    incidents = (await session.execute(base_stmt.order_by(Incident.last_seen_at.desc()).offset(offset).limit(safe_page_size))).scalars().all()

    items = []
    for incident in incidents:
        alert_count = int((await session.scalar(select(func.count()).select_from(Alert).where(Alert.incident_id == incident.id))) or 0)
        latest_event_type = (
            await session.execute(
                select(IncidentEvent.event_type)
                .where(IncidentEvent.stream_id == incident.id)
                .order_by(IncidentEvent.sequence_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        items.append(
            IncidentListItem(
                id=incident.id,
                fingerprint=incident.fingerprint,
                grouping_key=incident.grouping_key,
                dedup_key=incident.dedup_key,
                summary=incident.summary,
                severity=incident.severity.value,
                status=incident.status.value,
                first_seen_at=incident.first_seen_at,
                last_seen_at=incident.last_seen_at,
                acknowledged_at=incident.acknowledged_at,
                sla_deadline=incident.sla_deadline,
                sla_violated=incident.sla_violated,
                created_at=incident.created_at,
                updated_at=incident.updated_at,
                alert_count=alert_count,
                latest_event_type=latest_event_type,
                mttr_seconds=incident.mttr_seconds,
                projection_version=incident.projection_version,
            ).model_dump(mode='json')
        )

    return {'items': items, 'page': page, 'page_size': safe_page_size, 'total': total}


@router.get('/incidents/{incident_id}', response_model=IncidentOut)
async def get_incident(
    incident_id: str,
    alert_page: int = Query(default=1, ge=1),
    alert_page_size: int = Query(default=20, ge=1),
    session: AsyncSession = Depends(get_db),
) -> IncidentOut:
    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail='incident not found')

    safe_alert_page_size = clamp_page_size(alert_page_size, default=20, maximum=MAX_PAGE_SIZE)
    detail = await build_incident_detail(session, incident, safe_alert_page_size, (alert_page - 1) * safe_alert_page_size, timeline_limit=MAX_PAGE_SIZE)
    return IncidentOut(
        id=incident.id,
        fingerprint=incident.fingerprint,
        grouping_key=incident.grouping_key,
        dedup_key=incident.dedup_key,
        summary=incident.summary,
        severity=incident.severity.value,
        status=incident.status.value,
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
        projection_version=incident.projection_version,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        alerts=[AlertOut.model_validate(alert) for alert in detail['alerts']],
        timeline=[EventEnvelopeOut.model_validate(event) for event in detail['timeline']],
    )


@router.get('/incidents/{incident_id}/events/replay', response_model=IncidentReplayOut)
async def replay_incident_events(incident_id: str, session: AsyncSession = Depends(get_db)) -> IncidentReplayOut:
    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail='incident not found')
    state, events = await replay_incident_stream(session, incident.id)
    return IncidentReplayOut(
        incident_id=incident.id,
        total_events=len(events),
        replayed_state=state.model_dump(),
        events=[EventEnvelopeOut.model_validate(event) for event in events],
    )


@router.get('/dashboard', response_model=DashboardStats)
async def dashboard(session: AsyncSession = Depends(get_db)) -> DashboardStats:
    return DashboardStats(**await dashboard_counts(session))


@router.get('/alerts/recent')
async def recent_alerts(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> dict:
    alerts = await recent_alerts_summary(session, hours=hours, limit=limit)
    return {
        'hours': hours,
        'limit': limit,
        'items': [AlertOut.model_validate(alert).model_dump(mode='json') for alert in alerts],
    }
