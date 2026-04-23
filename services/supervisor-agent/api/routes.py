import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_async_session
from aiops_shared.http_client import RetryableHTTPClient
from aiops_shared.schemas import AnalyzeRequest
from aiops_shared.utils import health_payload

from core.analyzer import AnalysisService
from core.config import HTTP_BASE_DELAY, HTTP_MAX_RETRIES, HTTP_TIMEOUT, SERVICE_NAME

router = APIRouter()
logger = logging.getLogger(__name__)
http_client = RetryableHTTPClient(max_retries=HTTP_MAX_RETRIES, base_delay=HTTP_BASE_DELAY, timeout=HTTP_TIMEOUT)
service = AnalysisService(http_client)


@router.post('/analyze')
async def analyze(payload: AnalyzeRequest):
    try:
        return await service.analyze_incident(str(payload.incident_id))
    except Exception as exc:
        logger.exception('analysis failed', extra={'incident_id': str(payload.incident_id)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/health')
async def health(session: AsyncSession = Depends(get_async_session)):
    database = 'connected'
    try:
        await session.execute(text('SELECT 1'))
    except Exception:
        database = 'disconnected'
    return health_payload(SERVICE_NAME, database)
