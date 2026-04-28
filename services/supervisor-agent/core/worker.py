import asyncio
import logging

from sqlalchemy import func, select

from aiops_shared.database import get_session_factory
from aiops_shared.dlq import enqueue_dead_letter
from aiops_shared.dlq_worker import run_dlq_worker
from aiops_shared.metrics import AGENT_ACTIONS, QUEUE_DEPTH
from aiops_shared.models import EventQueue, Incident, QueueStatus
from aiops_shared.queue import claim_next_job, mark_job_complete, retry_job
from aiops_shared.http_client import AsyncServiceClient

from .analyzer import AnalysisService
from .config import HISTORY_AGENT_URL, HTTP_BACKOFF_SECONDS, HTTP_CIRCUIT_BREAKER_RESET_SECONDS, HTTP_CIRCUIT_BREAKER_THRESHOLD, HTTP_MAX_RETRIES, HTTP_TIMEOUT, SERVICE_NAME

logger = logging.getLogger(__name__)
http_client = AsyncServiceClient(
    timeout=HTTP_TIMEOUT,
    max_retries=HTTP_MAX_RETRIES,
    backoff_seconds=HTTP_BACKOFF_SECONDS,
    failure_threshold=HTTP_CIRCUIT_BREAKER_THRESHOLD,
    reset_timeout=HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    service_name=SERVICE_NAME,
)
analysis_service = AnalysisService()


async def run_supervisor_queue_worker(stop_event: asyncio.Event) -> None:
    session_factory = get_session_factory()
    while not stop_event.is_set():
        async with session_factory() as session:
            async with session.begin():
                job = await claim_next_job(session, 'supervisor.analyze')
                if job is None:
                    await asyncio.sleep(1.0)
                    continue
                try:
                    incident_id = job.payload['incident_id']
                    detail_response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
                    incident_bundle = detail_response.json()
                    incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one()
                    await analysis_service.analyze(
                        session,
                        incident,
                        incident_bundle,
                        reasoning_mode=job.payload.get('reasoning_mode', 'balanced'),
                        actor='supervisor-worker',
                        metadata={'queue_job_id': str(job.id), 'worker': SERVICE_NAME},
                        correlation_id=job.correlation_id,
                        idempotency_key=job.idempotency_key,
                    )
                    await mark_job_complete(session, job)
                    AGENT_ACTIONS.labels('supervisor-agent', 'queue_analyze_processed').inc()
                except Exception as exc:  # noqa: BLE001
                    logger.exception('queue job failed')
                    should_retry = await retry_job(session, job, str(exc))
                    if not should_retry:
                        await enqueue_dead_letter(
                            session,
                            service=SERVICE_NAME,
                            operation='queue.supervisor.analyze',
                            payload=job.payload,
                            error_message=str(exc),
                            correlation_id=job.correlation_id,
                            idempotency_key=job.idempotency_key,
                            queue_key=f'queue:{job.id}',
                        )
        await asyncio.sleep(0.5)


async def run_retry_worker(stop_event: asyncio.Event) -> None:
    session_factory = get_session_factory()
    while not stop_event.is_set():
        async with session_factory() as session:
            pending = await session.scalar(select(func.count()).select_from(EventQueue).where(EventQueue.status.in_([QueueStatus.PENDING, QueueStatus.RETRYING])))
            QUEUE_DEPTH.labels('supervisor.analyze').set(int(pending or 0))
        await asyncio.sleep(5.0)


async def run_supervisor_dlq_worker(stop_event: asyncio.Event) -> None:
    await run_dlq_worker(stop_event, service=SERVICE_NAME)
