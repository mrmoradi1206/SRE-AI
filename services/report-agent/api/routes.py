import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_async_session
from aiops_shared.http_client import RetryableHTTPClient
from aiops_shared.schemas import ReportRequest
from aiops_shared.utils import health_payload

from core.config import HISTORY_AGENT_URL, HTTP_BASE_DELAY, HTTP_MAX_RETRIES, HTTP_TIMEOUT, SERVICE_NAME
from core.formatter import ReportFormatter
from core.sender import WebhookSender

router = APIRouter()
logger = logging.getLogger(__name__)
http_client = RetryableHTTPClient(max_retries=HTTP_MAX_RETRIES, base_delay=HTTP_BASE_DELAY, timeout=HTTP_TIMEOUT)
formatter = ReportFormatter()
sender = WebhookSender(http_client)


@router.post('/report')
async def report(payload: ReportRequest):
    try:
        incident_response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{payload.incident_id}')
        incident_bundle = incident_response.json()
        incident = incident_bundle['incident']
        timeline_response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{payload.incident_id}/timeline')
        context = {'incident': incident, 'timeline': timeline_response.json()}
        rendered = formatter.render(context)
        delivery = await sender.send(rendered, incident['severity'])
        await http_client.post(f'{HISTORY_AGENT_URL}/internal/incidents/{payload.incident_id}/status', json={'status': 'reported'})
        return {'status': 'reported', 'delivery': delivery, 'report': rendered}
    except Exception as exc:
        logger.exception('report generation failed', extra={'incident_id': str(payload.incident_id)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/health')
async def health(session: AsyncSession = Depends(get_async_session)):
    database = 'connected'
    try:
        await session.execute(text('SELECT 1'))
    except Exception:
        database = 'disconnected'
    return health_payload(SERVICE_NAME, database)
