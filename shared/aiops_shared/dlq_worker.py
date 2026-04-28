import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session_factory
from .dlq import enqueue_dead_letter
from .metrics import DLQ_EVENTS
from .models import DeadLetterQueue, DeadLetterStatus
from .utils import utcnow

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = int(__import__('os').getenv('DLQ_MAX_RETRIES', '5'))
DEFAULT_BASE_DELAY_SECONDS = int(__import__('os').getenv('DLQ_BASE_DELAY_SECONDS', '60'))
DEFAULT_POLL_INTERVAL_SECONDS = float(__import__('os').getenv('DLQ_POLL_INTERVAL_SECONDS', '10'))
DEFAULT_BATCH_SIZE = int(__import__('os').getenv('DLQ_BATCH_SIZE', '10'))


async def claim_dlq_items(
    session: AsyncSession,
    service: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[DeadLetterQueue]:
    stmt = (
        select(DeadLetterQueue)
        .where(
            DeadLetterQueue.status.in_([DeadLetterStatus.PENDING, DeadLetterStatus.RETRYING]),
            DeadLetterQueue.next_retry_at <= utcnow(),
        )
        .order_by(DeadLetterQueue.next_retry_at.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
    )
    if service:
        stmt = stmt.where(DeadLetterQueue.service == service)
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    for item in items:
        item.status = DeadLetterStatus.RETRYING
    await session.flush()
    return items


async def mark_dlq_success(session: AsyncSession, item: DeadLetterQueue) -> None:
    item.status = DeadLetterStatus.PROCESSED
    item.next_retry_at = None
    item.last_error = None
    await session.flush()
    DLQ_EVENTS.labels(item.service, item.operation).inc()


async def mark_dlq_failed(
    session: AsyncSession,
    item: DeadLetterQueue,
    error_message: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay_seconds: int = DEFAULT_BASE_DELAY_SECONDS,
) -> bool:
    item.retry_count += 1
    item.last_error = error_message
    if item.retry_count >= max_retries:
        item.status = DeadLetterStatus.FAILED
        item.next_retry_at = None
        await session.flush()
        logger.warning(
            'dlq_item_exhausted',
            extra={
                'queue_key': item.queue_key,
                'service': item.service,
                'operation': item.operation,
                'retry_count': item.retry_count,
            },
        )
        return False
    delay = base_delay_seconds * (2 ** item.retry_count)
    item.next_retry_at = utcnow() + timedelta(seconds=delay)
    item.status = DeadLetterStatus.RETRYING
    await session.flush()
    return True


async def run_dlq_worker(
    stop_event: asyncio.Event,
    *,
    service: str | None = None,
    processor: asyncio.abc.Coroutine | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay_seconds: int = DEFAULT_BASE_DELAY_SECONDS,
) -> None:
    session_factory = get_session_factory()
    while not stop_event.is_set():
        async with session_factory() as session:
            async with session.begin():
                items = await claim_dlq_items(session, service=service, batch_size=batch_size)
            if not items:
                await asyncio.sleep(poll_interval)
                continue
            for item in items:
                if stop_event.is_set():
                    return
                try:
                    if processor is not None:
                        await processor(item)
                    else:
                        await _default_process_dlq_item(item)
                    async with session.begin():
                        await mark_dlq_success(session, item)
                except Exception as exc:  # noqa: BLE001
                    logger.exception('dlq_item_failed', extra={'queue_key': item.queue_key, 'service': item.service})
                    async with session.begin():
                        await mark_dlq_failed(
                            session,
                            item,
                            str(exc),
                            max_retries=max_retries,
                            base_delay_seconds=base_delay_seconds,
                        )
        await asyncio.sleep(0.5)


async def _default_process_dlq_item(item: DeadLetterQueue) -> None:
    logger.info('dlq_item_processed', extra={'queue_key': item.queue_key, 'service': item.service, 'operation': item.operation})
