import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_async_session
from aiops_shared.http_client import RetryableHTTPClient
from aiops_shared.schemas import AlertResponse, AlertWebhookRequest
from aiops_shared.utils import health_payload

from core.config import HTTP_BASE_DELAY, HTTP_MAX_RETRIES, HTTP_TIMEOUT, SERVICE_NAME, SUPERVISOR_AGENT_URL
from core.search import search_by_fingerprint
from core.storage import fetch_incidents, fetch_timeline, store_alert, update_incident_analysis, update_incident_status

router = APIRouter()
logger = logging.getLogger(__name__)
http_client = RetryableHTTPClient(max_retries=HTTP_MAX_RETRIES, base_delay=HTTP_BASE_DELAY, timeout=HTTP_TIMEOUT)


async def trigger_supervisor(incident_id: str) -> None:
    try:
        await http_client.post(f'{SUPERVISOR_AGENT_URL}/analyze', json={'incident_id': incident_id})
    except Exception as exc:
        logger.exception('failed to trigger supervisor', extra={'incident_id': incident_id, 'error': str(exc)})


@router.post('/alerts', response_model=AlertResponse)
async def receive_alerts(payload: AlertWebhookRequest, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_async_session)):
    if not payload.alerts:
        raise HTTPException(status_code=400, detail='alerts list cannot be empty')
    stored_alert, incident, is_new = await store_alert(session, payload.alerts[0])
    background_tasks.add_task(trigger_supervisor, str(incident.id))
    return AlertResponse(incident_id=incident.id, alert_id=stored_alert.id, is_new_incident=is_new, fingerprint=stored_alert.fingerprint)


@router.get('/alerts/search')
async def search_alerts(fingerprint: str, hours: int = 24, session: AsyncSession = Depends(get_async_session)):
    context = await search_by_fingerprint(session, fingerprint, hours)
    if context is None:
        raise HTTPException(status_code=404, detail='incident not found')
    return context


@router.get('/incidents')
async def list_incidents(session: AsyncSession = Depends(get_async_session)):
    return await fetch_incidents(session)


@router.get('/incidents/{incident_id}/timeline')
async def incident_timeline(incident_id: UUID, session: AsyncSession = Depends(get_async_session)):
    return await fetch_timeline(session, incident_id)


@router.get('/incidents/{incident_id}')
async def get_incident(incident_id: UUID, session: AsyncSession = Depends(get_async_session)):
    incidents = await fetch_incidents(session)
    incident = next((item for item in incidents if item['id'] == str(incident_id)), None)
    if incident is None:
        raise HTTPException(status_code=404, detail='incident not found')
    context = await search_by_fingerprint(session, incident['fingerprint'], 24)
    if context is None:
        raise HTTPException(status_code=404, detail='incident context not found')
    return {'incident': context['incident'], 'timeline': context['timeline']}


@router.post('/internal/incidents/{incident_id}/analysis')
async def save_analysis(incident_id: UUID, analysis: dict, session: AsyncSession = Depends(get_async_session)):
    await update_incident_analysis(session, incident_id, analysis)
    return {'status': 'ok'}


@router.post('/internal/incidents/{incident_id}/status')
async def save_status(incident_id: UUID, payload: dict, session: AsyncSession = Depends(get_async_session)):
    await update_incident_status(session, incident_id, payload['status'])
    return {'status': 'ok'}


@router.get('/health')
async def health(session: AsyncSession = Depends(get_async_session)):
    database = 'connected'
    try:
        await session.execute(text('SELECT 1'))
    except Exception:
        database = 'disconnected'
    return health_payload(SERVICE_NAME, database)
