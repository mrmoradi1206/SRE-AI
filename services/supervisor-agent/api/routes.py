import hashlib
import hmac
import json
import os
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_db
from aiops_shared.context_loader import normalize_incident_bundle
from aiops_shared.dlq import enqueue_dead_letter
from aiops_shared.event_store import append_event
from aiops_shared.idempotency import ensure_idempotency_key, get_existing_event_by_idempotency
from aiops_shared.models import DeadLetterQueue, EventQueue, Incident, IncidentStatus
from aiops_shared.schemas import AISettingsIn, AISettingsOut, DeadLetterOut, QueueItemOut, RuntimeSecretsIn, SupervisorAnalyzeIn, SupervisorStatusChangeIn, TestWorkflowIn
from aiops_shared.secret_store import SecretStoreError, get_runtime_secret, save_runtime_secrets
from aiops_shared.utils import health_payload, utcnow
from aiops_shared.http_client import AsyncServiceClient
from aiops_shared.llm_client import LLMError, run_llm
from aiops_shared.llm_config import LLMConfigError, get_agent_llm_config, load_llm_config, save_llm_config
from aiops_shared.fsm import apply_transition
from aiops_shared.projector import apply_event_to_projection
from aiops_shared.queue import enqueue_job

from core.analyzer import AnalysisService
from core.memory import ReActMemory
from core.rag import IncidentRAG
from core.config import (
    HISTORY_AGENT_URL,
    HTTP_BACKOFF_SECONDS,
    HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    HTTP_CIRCUIT_BREAKER_THRESHOLD,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    REPORT_AGENT_URL,
    SERVICE_NAME,
)

router = APIRouter(prefix='/supervisor')
plain_router = APIRouter()
service = AnalysisService()
react_memory = ReActMemory()
incident_rag = IncidentRAG()


class IncidentApproveIn(BaseModel):
    root_cause: str = Field(min_length=3, max_length=8000)
    resolution: str = Field(min_length=3, max_length=8000)
    summary: str | None = Field(default=None, max_length=2000)
    service: str | None = Field(default=None, max_length=200)
    severity: str | None = Field(default=None, max_length=80)

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
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _event_metadata(event) -> dict:
    return getattr(event, 'event_metadata', {}) or {}


def _step(name: str, started: float, status: str, **extra) -> dict:
    return {'name': name, 'status': status, 'duration_ms': round((time.perf_counter() - started) * 1000, 2), **extra}


def _signed_alert_request(alert_payload: dict, workflow_id: str) -> dict:
    body = json.dumps(alert_payload, separators=(',', ':'), default=str).encode('utf-8')
    headers = {'Idempotency-Key': f'test-workflow:history:{workflow_id}', 'Content-Type': 'application/json'}
    secret = os.getenv('ALERT_WEBHOOK_SECRET')
    if secret:
        signature = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        headers['X-SRE-AI-Signature'] = f'sha256={signature}'
    return {'content': body, 'headers': headers}


async def _with_similar_incidents(incident_bundle: dict) -> dict:
    bundle = normalize_incident_bundle(incident_bundle)
    incident = bundle.get('incident', {})
    query = incident.get('summary') or incident.get('fingerprint') or incident.get('grouping_key')
    if not query:
        return incident_bundle
    try:
        response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents', params={'query': query, 'page': 1, 'page_size': 5})
        similar = response.json().get('items', [])
    except Exception:  # noqa: BLE001
        similar = []
    bundle['similar_incidents'] = [item for item in similar if str(item.get('id')) != str(incident.get('id'))]
    return bundle


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




@plain_router.get('/config/llm')
async def get_llm_config() -> dict:
    try:
        return load_llm_config()
    except LLMConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@plain_router.post('/config/llm')
async def update_llm_config(payload: dict) -> dict:
    try:
        return save_llm_config(payload)
    except LLMConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail='failed to save LLM config') from exc


@plain_router.post('/config/llm/test/{agent_name}')
async def test_llm_config(agent_name: str) -> dict:
    try:
        selection = get_agent_llm_config(agent_name)
        response = await run_llm(
            selection['provider'],
            selection['model'],
            [
                {'role': 'system', 'content': 'You are an SRE-AI connectivity test. Reply with compact JSON.'},
                {'role': 'user', 'content': f'Return JSON confirming that the {agent_name} agent LLM route works.'},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        return {
            'agent': agent_name,
            'provider': response['provider'],
            'model': response['model'],
            'ok': True,
            'content': response['content'],
        }
    except LLMConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail={'provider': exc.provider, 'model': exc.model, 'message': exc.message, 'retryable': exc.retryable}) from exc


@plain_router.get('/config/llm/secrets')
async def get_runtime_secret_status() -> dict:
    config = load_llm_config()
    status = {}
    for provider, settings in config.get('provider_settings', {}).items():
        env_name = settings.get('api_key_env')
        if not env_name:
            continue
        try:
            runtime_configured = bool(get_runtime_secret(env_name))
        except SecretStoreError:
            runtime_configured = False
        status[provider] = {
            'api_key_env': env_name,
            'configured': runtime_configured,
            'env_configured': bool(os.getenv(env_name)),
        }
    return {'providers': status}


@plain_router.post('/config/llm/secrets')
async def update_runtime_secrets(payload: RuntimeSecretsIn) -> dict:
    try:
        saved = save_runtime_secrets(payload.secrets)
    except SecretStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {'saved': {key: bool(value) for key, value in saved.items()}}


@plain_router.post('/test-workflow')
async def test_workflow(payload: TestWorkflowIn, request: Request, session: AsyncSession = Depends(get_db)) -> dict:
    trace: list[dict] = []
    workflow_id = str(uuid4())
    alert_payload = payload.alert.model_dump(mode='json', exclude_none=True)

    started = time.perf_counter()
    try:
        alert_request = _signed_alert_request(alert_payload, workflow_id)
        ingest_response = await http_client.post(
            f'{HISTORY_AGENT_URL}/alerts',
            **alert_request,
        )
        ingestion = ingest_response.json()
        incident_id = ingestion.get('incident_id')
        trace.append(_step('history.ingest', started, 'ok', incident_id=incident_id))
    except Exception as exc:  # noqa: BLE001
        trace.append(_step('history.ingest', started, 'error', error=str(exc)))
        return {'workflow_id': workflow_id, 'status': 'failed', 'trace': trace}

    started = time.perf_counter()
    try:
        detail_response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
        incident_bundle = await _with_similar_incidents(detail_response.json())
        trace.append(_step('history.context', started, 'ok'))
    except Exception as exc:  # noqa: BLE001
        trace.append(_step('history.context', started, 'error', error=str(exc)))
        return {'workflow_id': workflow_id, 'status': 'failed', 'incident_id': incident_id, 'history': ingestion, 'trace': trace}

    started = time.perf_counter()
    try:
        async with session.begin():
            incident = (await session.execute(select(Incident).where(Incident.id == UUID(str(incident_id))))).scalar_one_or_none()
            if incident is None:
                raise LookupError('incident not found after ingestion')
            decision = await service.analyze(
                session,
                incident,
                incident_bundle,
                reasoning_mode='balanced',
                actor='test-workflow',
                metadata=_metadata(request) | {'workflow_id': workflow_id},
                correlation_id=_correlation_uuid(request),
                idempotency_key=f'test-workflow:supervisor:{workflow_id}',
            )
        trace.append(_step('supervisor.analyze', started, 'ok', provider=decision.get('provider'), model=decision.get('model')))
    except Exception as exc:  # noqa: BLE001
        trace.append(_step('supervisor.analyze', started, 'error', error=str(exc)))
        return {'workflow_id': workflow_id, 'status': 'failed', 'incident_id': incident_id, 'history': ingestion, 'trace': trace}

    started = time.perf_counter()
    try:
        report_response = await http_client.post(
            f'{REPORT_AGENT_URL}/report/{incident_id}',
            json={'analysis': decision},
            headers={'Idempotency-Key': f'test-workflow:report:{workflow_id}'},
            timeout=max(HTTP_TIMEOUT, 150.0),
        )
        report = report_response.json()
        trace.append(_step('report.generate', started, 'ok', provider=report.get('provider'), model=report.get('model')))
    except Exception as exc:  # noqa: BLE001
        trace.append(_step('report.generate', started, 'error', error=str(exc)))
        return {
            'workflow_id': workflow_id,
            'status': 'failed',
            'incident_id': incident_id,
            'history': ingestion,
            'supervisor': decision,
            'trace': trace,
            'llm_calls': [decision.get('llm_trace')],
        }

    return {
        'workflow_id': workflow_id,
        'status': 'ok',
        'incident_id': incident_id,
        'history': ingestion,
        'supervisor': decision,
        'report': report,
        'trace': trace,
        'llm_calls': [item for item in [decision.get('llm_trace'), report.get('llm_trace')] if item],
    }


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
            return {'incident_id': str(payload.incident_id), 'deduplicated': True, **_event_metadata(existing).get('reasoning_output', existing.payload)}

    try:
        detail_response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{payload.incident_id}')
        incident_bundle = await _with_similar_incidents(detail_response.json())
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






def _service_from_bundle(bundle: dict) -> str | None:
    alerts = bundle.get('alerts') or []
    latest = alerts[0].get('payload', {}) if alerts else {}
    labels = latest.get('labels', {}) if isinstance(latest, dict) else {}
    return labels.get('service') or labels.get('job') or labels.get('app') or labels.get('alertname')


def _rag_query_from_bundle(bundle: dict) -> str:
    incident = bundle.get('incident', {})
    alerts = bundle.get('alerts', [])[:3]
    return json.dumps({'incident': incident, 'alerts': alerts}, default=str)


async def _similar_incidents_payload(session: AsyncSession, incident_id: str, limit: int = 5) -> dict:
    response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
    bundle = normalize_incident_bundle(response.json())
    items = await incident_rag.retrieve_similar_incidents(
        session,
        query_text=_rag_query_from_bundle(bundle),
        incident_id=incident_id,
        limit=limit,
    )
    return {'incident_id': incident_id, 'items': items, 'count': len(items)}

async def _incident_trace_payload(incident_id: str) -> dict:
    history = await react_memory.get_history(incident_id, limit=50)
    return {
        'incident_id': incident_id,
        'memory_key': incident_id,
        'steps': history,
        'count': len(history),
    }


@plain_router.get('/api/v1/incidents/{incident_id}/trace')
async def incident_trace_v1(incident_id: str) -> dict:
    return await _incident_trace_payload(incident_id)



@plain_router.get('/api/v1/incidents/{incident_id}/similar')
async def incident_similar_v1(incident_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    return await _similar_incidents_payload(session, incident_id)


@plain_router.post('/api/v1/incidents/{incident_id}/approve')
async def approve_incident_v1(incident_id: str, payload: IncidentApproveIn, request: Request, session: AsyncSession = Depends(get_db)) -> dict:
    response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
    bundle = normalize_incident_bundle(response.json())
    incident = bundle.get('incident', {})
    saved = await incident_rag.save_resolved_incident(
        session,
        incident_id=incident_id,
        summary=payload.summary or incident.get('summary') or incident.get('fingerprint') or 'Approved incident',
        root_cause=payload.root_cause,
        resolution=payload.resolution,
        service=payload.service or _service_from_bundle(bundle),
        severity=payload.severity or incident.get('severity'),
        metadata=_metadata(request) | {'approved_by': 'human-sre'},
    )
    await session.commit()
    return {'saved': True, 'knowledge': saved}

@router.get('/incidents/{incident_id}')
async def supervisor_view(incident_id: str) -> dict:
    response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
    return response.json()




@router.get('/incidents/{incident_id}/trace')
async def supervisor_incident_trace(incident_id: str) -> dict:
    return await _incident_trace_payload(incident_id)



@router.get('/incidents/{incident_id}/similar')
async def supervisor_incident_similar(incident_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    return await _similar_incidents_payload(session, incident_id)


@router.post('/incidents/{incident_id}/approve')
async def supervisor_incident_approve(incident_id: str, payload: IncidentApproveIn, request: Request, session: AsyncSession = Depends(get_db)) -> dict:
    return await approve_incident_v1(incident_id, payload, request, session)

@router.get('/settings', response_model=AISettingsOut)
async def get_settings(session: AsyncSession = Depends(get_db)) -> AISettingsOut:
    return await service.current_settings(session)


@router.put('/settings', response_model=AISettingsOut)
async def update_settings(payload: AISettingsIn, session: AsyncSession = Depends(get_db)) -> AISettingsOut:
    config = load_llm_config()
    config['agents']['supervisor'] = {'provider': payload.provider, 'model': payload.model}
    saved = save_llm_config(config)
    selection = saved['agents']['supervisor']
    return AISettingsOut(id=None, provider=selection['provider'], model=selection['model'], api_key=None, extra_config={}, version=None)


@router.get('/dlq', response_model=list[DeadLetterOut])
async def list_dlq(session: AsyncSession = Depends(get_db)) -> list[DeadLetterOut]:
    items = (await session.execute(select(DeadLetterQueue).order_by(DeadLetterQueue.created_at.desc()).limit(100))).scalars().all()
    return [DeadLetterOut.model_validate(item) for item in items]


@router.get('/queue', response_model=list[QueueItemOut])
async def list_queue(session: AsyncSession = Depends(get_db)) -> list[QueueItemOut]:
    items = (await session.execute(select(EventQueue).order_by(EventQueue.created_at.desc()).limit(100))).scalars().all()
    return [QueueItemOut.model_validate(item) for item in items]
