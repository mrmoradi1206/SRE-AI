from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .metrics import DLQ_EVENTS
from .models import DeadLetterQueue, DeadLetterStatus
from .utils import utcnow


async def enqueue_dead_letter(
    session: AsyncSession,
    *,
    service: str,
    operation: str,
    payload: dict,
    error_message: str,
    correlation_id: UUID | None = None,
    idempotency_key: str | None = None,
    queue_key: str | None = None,
) -> DeadLetterQueue:
    key = queue_key or f'{service}:{operation}:{idempotency_key or uuid4()}'
    existing = (
        await session.execute(select(DeadLetterQueue).where(DeadLetterQueue.queue_key == key))
    ).scalar_one_or_none()
    if existing is not None:
        existing.retry_count += 1
        existing.status = DeadLetterStatus.RETRYING
        existing.error_message = error_message
        existing.next_retry_at = utcnow() + timedelta(minutes=5)
        return existing

    item = DeadLetterQueue(
        queue_key=key,
        service=service,
        operation=operation,
        status=DeadLetterStatus.PENDING,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload=payload,
        error_message=error_message,
        retry_count=0,
        next_retry_at=utcnow() + timedelta(minutes=5),
    )
    session.add(item)
    await session.flush()
    DLQ_EVENTS.labels(service, operation).inc()
    return item
