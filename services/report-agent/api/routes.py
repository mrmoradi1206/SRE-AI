from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_db
from aiops_shared.dlq import enqueue_dead_letter
from aiops_shared.event_store import append_event
from aiops_shared.http_client import AsyncServiceClient
from aiops_shared.idempotency import ensure_idempotency_key, get_existing_event_by_idempotency
from aiops_shared.metrics import AGENT_ACTIONS
from aiops_shared.models import AISettings, Incident, IncidentEvent
from aiops_shared.utils import health_payload

from core.config import (
    AI_MODEL,
    AI_PROVIDER,
    HISTORY_AGENT_URL,
    HTTP_BACKOFF_SECONDS,
    HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    HTTP_CIRCUIT_BREAKER_THRESHOLD,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERVICE_NAME,
)
from core.formatter import ReportFormatter

router = APIRouter()
formatter = ReportFormatter()
http_client = AsyncServiceClient(
    timeout=HTTP_TIMEOUT,
    max_retries=HTTP_MAX_RETRIES,
    backoff_seconds=HTTP_BACKOFF_SECONDS,
    failure_threshold=HTTP_CIRCUIT_BREAKER_THRESHOLD,
    reset_timeout=HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    service_name=SERVICE_NAME,
)


def _metadata(request: Request) -> dict:
    return {
        'request_id': getattr(request.state, 'request_id', None),
        'trace_id': getattr(request.state, 'trace_id', None),
        'correlation_id': getattr(request.state, 'correlation_id', None),
        'path': str(request.url.path),
        'method': request.method,
    }


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


@router.post('/report/{incident_id}')
async def generate_report(
    incident_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    session: AsyncSession = Depends(get_db),
) -> dict:
    effective_idempotency_key = ensure_idempotency_key(idempotency_key, f'report:{incident_id}')
    async with session.begin():
        existing = await get_existing_event_by_idempotency(session, effective_idempotency_key)
        if existing is not None:
            return {'incident_id': incident_id, 'report': existing.payload.get('report'), 'deduplicated': True}

    try:
        response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
        incident_bundle = response.json()
    except Exception as exc:
        async with session.begin():
            await enqueue_dead_letter(
                session,
                service=SERVICE_NAME,
                operation='generate_report.fetch_incident',
                payload={'incident_id': incident_id},
                error_message=str(exc),
                correlation_id=UUID(str(getattr(request.state, 'correlation_id', None))) if getattr(request.state, 'correlation_id', None) else None,
                idempotency_key=effective_idempotency_key,
            )
        raise HTTPException(status_code=502, detail='failed to fetch incident context') from exc

    settings = (await session.execute(select(AISettings).order_by(AISettings.id.asc()).limit(1))).scalar_one_or_none()
    report_text = await formatter.render(incident_bundle, provider=AI_PROVIDER, model=AI_MODEL, settings=settings)

    async with session.begin():
        incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
        if incident is None:
            raise HTTPException(status_code=404, detail='incident not found')
        event = await append_event(
            session,
            stream_id=incident.id,
            event_type='report.report_generated',
            actor='report-agent',
            correlation_id=UUID(str(getattr(request.state, 'correlation_id', None))) if getattr(request.state, 'correlation_id', None) else None,
            idempotency_key=effective_idempotency_key,
            payload={'report': report_text, 'provider': AI_PROVIDER, 'model': AI_MODEL},
            metadata=_metadata(request),
        )
    AGENT_ACTIONS.labels('report-agent', 'report_generated').inc()
    return {'incident_id': incident_id, 'report': report_text, 'event_id': str(event.event_id)}


@router.get('/report/{incident_id}')
async def get_latest_report(incident_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    event = (
        await session.execute(
            select(IncidentEvent)
            .where(IncidentEvent.stream_id == incident_id, IncidentEvent.event_type == 'report.report_generated')
            .order_by(IncidentEvent.sequence_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail='report not found')
    return {'incident_id': incident_id, 'report_event': event.payload, 'created_at': event.created_at, 'event_id': event.event_id}
