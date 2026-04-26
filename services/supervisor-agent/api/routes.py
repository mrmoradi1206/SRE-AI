from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_db
from aiops_shared.dlq import enqueue_dead_letter
from aiops_shared.event_store import append_event
from aiops_shared.idempotency import ensure_idempotency_key, get_existing_event_by_idempotency
from aiops_shared.models import AISettings, DeadLetterQueue, Incident, IncidentStatus
from aiops_shared.schemas import AISettingsIn, AISettingsOut, DeadLetterOut, QueueItemOut, SupervisorAnalyzeIn, SupervisorStatusChangeIn
from aiops_shared.utils import health_payload, utcnow
from aiops_shared.http_client import AsyncServiceClient
from aiops_shared.fsm import apply_transition
from aiops_shared.projector import apply_event_to_projection
from aiops_shared.queue import enqueue_job
from aiops_shared.models import EventQueue

from core.analyzer import AnalysisService
from core.config import (
    HISTORY_AGENT_URL,
    HTTP_BACKOFF_SECONDS,
    HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    HTTP_CIRCUIT_BREAKER_THRESHOLD,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERVICE_NAME,
)

router = APIRouter(prefix='/supervisor')
plain_router = APIRouter()
service = AnalysisService()
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


def _correlation_uuid(request: Request) -> UUID | None:
    raw = getattr(request.state, 'correlation_id', None)
    return UUID(str(raw)) if raw else None


@plain_router.get('/health')
async def health(session: AsyncSession = Depends(get_db)) -> dict:
    database = 'connected'
    try:
        await session.execute(text('SELECT 1'))
    except Exception:
        database = 'disconnected'
    return health_payload(SERVICE_NAME, database, readiness=database)


@plain_router.get('/ready')
async def ready(session: AsyncSession = Depends(get_db)) -> dict:
    try:
        await session.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='database unavailable') from exc
    return health_payload(SERVICE_NAME, 'connected', readiness='ready')


@router.post('/analyze')
async def analyze(
    payload: SupervisorAnalyzeIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    session: AsyncSession = Depends(get_db),
) -> dict:
    effective_idempotency_key = ensure_idempotency_key(idempotency_key, f'supervisor:analyze:{payload.incident_id}')
    async with session.begin():
        existing = await get_existing_event_by_idempotency(session, effective_idempotency_key)
        if existing is not None:
            return {'incident_id': str(payload.incident_id), 'deduplicated': True, **existing.metadata.get('reasoning_output', existing.payload)}

    try:
        detail_response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{payload.incident_id}')
        incident_bundle = detail_response.json()
    except Exception as exc:
        async with session.begin():
            await enqueue_dead_letter(
                session,
                service=SERVICE_NAME,
                operation='analyze.fetch_incident',
                payload={'incident_id': str(payload.incident_id)},
                error_message=str(exc),
                correlation_id=_correlation_uuid(request),
                idempotency_key=effective_idempotency_key,
            )
        raise HTTPException(status_code=502, detail='failed to fetch incident context') from exc

    async with session.begin():
        incident = (await session.execute(select(Incident).where(Incident.id == payload.incident_id))).scalar_one_or_none()
        if incident is None:
            raise HTTPException(status_code=404, detail='incident not found')
        decision = await service.analyze(
            session,
            incident,
            incident_bundle,
            reasoning_mode=payload.reasoning_mode,
            actor='supervisor',
            metadata=_metadata(request),
            correlation_id=_correlation_uuid(request),
            idempotency_key=effective_idempotency_key,
        )
    return {'incident_id': str(payload.incident_id), **decision}


async def _change_status(
    session: AsyncSession,
    *,
    incident_id: str,
    target_status: IncidentStatus,
    reason: str | None,
    actor: str,
    metadata: dict,
    correlation_id: UUID | None,
    idempotency_key: str | None,
) -> dict:
    existing = await get_existing_event_by_idempotency(session, idempotency_key)
    if existing is not None:
        return {'incident_id': incident_id, 'status': existing.payload.get('to') or target_status.value, 'changed': False, 'deduplicated': True}

    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail='incident not found')

    transition = apply_transition(incident, target_status, actor, reason or f'manual transition to {target_status.value}', utcnow())
    if not transition.changed:
        return {'incident_id': incident_id, 'status': target_status.value, 'changed': False}

    status_event = await append_event(
        session,
        stream_id=incident.id,
        event_type='supervisor.status_changed',
        actor='supervisor',
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload={'from': transition.from_status, 'to': transition.to_status, 'reason': transition.reason},
        metadata=metadata | {'actor': actor},
    )
    await apply_event_to_projection(session, incident, status_event)
    await append_event(
        session,
        stream_id=incident.id,
        event_type='supervisor.action_recorded',
        actor='supervisor',
        correlation_id=correlation_id,
        payload={'decision': transition.to_status, 'reason': transition.reason},
        metadata=metadata | {'actor': actor},
    )
    return {'incident_id': incident_id, 'status': target_status.value, 'changed': True}


@router.post('/investigate')
async def investigate(payload: SupervisorStatusChangeIn, request: Request, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), session: AsyncSession = Depends(get_db)) -> dict:
    async with session.begin():
        return await _change_status(
            session,
            incident_id=str(payload.incident_id),
            target_status=IncidentStatus.INVESTIGATING,
            reason=payload.reason,
            actor=payload.actor,
            metadata=_metadata(request),
            correlation_id=_correlation_uuid(request),
            idempotency_key=ensure_idempotency_key(idempotency_key, f'supervisor:investigate:{payload.incident_id}'),
        )


@router.post('/mitigate')
async def mitigate(payload: SupervisorStatusChangeIn, request: Request, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), session: AsyncSession = Depends(get_db)) -> dict:
    async with session.begin():
        return await _change_status(
            session,
            incident_id=str(payload.incident_id),
            target_status=IncidentStatus.MITIGATING,
            reason=payload.reason,
            actor=payload.actor,
            metadata=_metadata(request),
            correlation_id=_correlation_uuid(request),
            idempotency_key=ensure_idempotency_key(idempotency_key, f'supervisor:mitigate:{payload.incident_id}'),
        )


@router.post('/resolve')
async def resolve(payload: SupervisorStatusChangeIn, request: Request, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), session: AsyncSession = Depends(get_db)) -> dict:
    async with session.begin():
        return await _change_status(
            session,
            incident_id=str(payload.incident_id),
            target_status=IncidentStatus.RESOLVED,
            reason=payload.reason,
            actor=payload.actor,
            metadata=_metadata(request),
            correlation_id=_correlation_uuid(request),
            idempotency_key=ensure_idempotency_key(idempotency_key, f'supervisor:resolve:{payload.incident_id}'),
        )


@router.post('/close')
async def close(payload: SupervisorStatusChangeIn, request: Request, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), session: AsyncSession = Depends(get_db)) -> dict:
    async with session.begin():
        return await _change_status(
            session,
            incident_id=str(payload.incident_id),
            target_status=IncidentStatus.CLOSED,
            reason=payload.reason,
            actor=payload.actor,
            metadata=_metadata(request),
            correlation_id=_correlation_uuid(request),
            idempotency_key=ensure_idempotency_key(idempotency_key, f'supervisor:close:{payload.incident_id}'),
        )


@router.post('/acknowledge')
async def acknowledge(payload: SupervisorStatusChangeIn, request: Request, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), session: AsyncSession = Depends(get_db)) -> dict:
    return await investigate(payload, request, idempotency_key=idempotency_key, session=session)


@router.post('/queue/analyze')
async def queue_analyze(payload: SupervisorAnalyzeIn, request: Request, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), session: AsyncSession = Depends(get_db)) -> dict:
    effective_idempotency_key = ensure_idempotency_key(idempotency_key, f'queue:supervisor:analyze:{payload.incident_id}')
    async with session.begin():
        job = await enqueue_job(
            session,
            topic='supervisor.analyze',
            payload={'incident_id': str(payload.incident_id), 'reasoning_mode': payload.reasoning_mode},
            stream_id=payload.incident_id,
            correlation_id=_correlation_uuid(request),
            idempotency_key=effective_idempotency_key,
        )
    return {'queued': True, 'job_id': str(job.id)}


@router.get('/incidents/{incident_id}')
async def supervisor_view(incident_id: str) -> dict:
    response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
    return response.json()


@router.get('/settings', response_model=AISettingsOut)
async def get_settings(session: AsyncSession = Depends(get_db)) -> AISettingsOut:
    return await service.current_settings(session)


@router.put('/settings', response_model=AISettingsOut)
async def update_settings(payload: AISettingsIn, session: AsyncSession = Depends(get_db)) -> AISettingsOut:
    async with session.begin():
        settings = (await session.execute(select(AISettings).order_by(AISettings.id.asc()).limit(1))).scalar_one_or_none()
        if settings is None:
            settings = AISettings(provider=payload.provider, model=payload.model, api_key=payload.api_key, extra_config=payload.extra_config, version=1)
            session.add(settings)
            await session.flush()
        else:
            settings.provider = payload.provider
            settings.model = payload.model
            settings.api_key = payload.api_key
            settings.extra_config = payload.extra_config
            settings.version += 1
    return AISettingsOut(id=settings.id, provider=settings.provider, model=settings.model, api_key=settings.api_key, extra_config=settings.extra_config, version=settings.version)


@router.get('/dlq', response_model=list[DeadLetterOut])
async def list_dlq(session: AsyncSession = Depends(get_db)) -> list[DeadLetterOut]:
    items = (await session.execute(select(DeadLetterQueue).order_by(DeadLetterQueue.created_at.desc()).limit(100))).scalars().all()
    return [DeadLetterOut.model_validate(item) for item in items]


@router.get('/queue', response_model=list[QueueItemOut])
async def list_queue(session: AsyncSession = Depends(get_db)) -> list[QueueItemOut]:
    items = (await session.execute(select(EventQueue).order_by(EventQueue.created_at.desc()).limit(100))).scalars().all()
    return [QueueItemOut.model_validate(item) for item in items]
