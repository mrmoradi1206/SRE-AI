import os
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EventQueue, QueueStatus
from .utils import utcnow


class BackpressureExceededError(RuntimeError):
    pass


async def enqueue_job(
    session: AsyncSession,
    *,
    topic: str,
    payload: dict,
    stream_id: UUID | None = None,
    correlation_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> EventQueue:
    max_pending = int(os.getenv('QUEUE_MAX_PENDING_PER_TOPIC', '2000'))
    if idempotency_key:
        existing = (
            await session.execute(select(EventQueue).where(EventQueue.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    if stream_id is not None:
        existing_stream_job = (
            await session.execute(
                select(EventQueue).where(
                    EventQueue.topic == topic,
                    EventQueue.stream_id == stream_id,
                    EventQueue.status.in_([QueueStatus.PENDING, QueueStatus.PROCESSING, QueueStatus.RETRYING]),
                )
            )
        ).scalar_one_or_none()
        if existing_stream_job is not None:
            return existing_stream_job
    pending = await session.scalar(
        select(func.count()).select_from(EventQueue).where(
            EventQueue.topic == topic,
            EventQueue.status.in_([QueueStatus.PENDING, QueueStatus.PROCESSING, QueueStatus.RETRYING]),
        )
    )
    if int(pending or 0) >= max_pending:
        raise BackpressureExceededError(f'queue backlog for {topic} exceeded {max_pending}')
    job = EventQueue(
        topic=topic,
        payload=payload,
        stream_id=stream_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        status=QueueStatus.PENDING,
    )
    session.add(job)
    await session.flush()
    return job


async def claim_next_job(session: AsyncSession, topic: str) -> EventQueue | None:
    result = await session.execute(
        select(EventQueue)
        .where(
            EventQueue.topic == topic,
            EventQueue.status.in_([QueueStatus.PENDING, QueueStatus.RETRYING]),
            EventQueue.not_before <= utcnow(),
        )
        .order_by(EventQueue.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = QueueStatus.PROCESSING
    await session.flush()
    return job


async def mark_job_complete(session: AsyncSession, job: EventQueue) -> None:
    job.status = QueueStatus.COMPLETED
    job.last_error = None
    await session.flush()


async def retry_job(session: AsyncSession, job: EventQueue, error_message: str, delay_seconds: int = 30, max_retries: int = 5) -> bool:
    job.retry_count += 1
    job.last_error = error_message
    if job.retry_count >= max_retries:
        job.status = QueueStatus.FAILED
        await session.flush()
        return False
    job.status = QueueStatus.RETRYING
    job.not_before = utcnow() + timedelta(seconds=delay_seconds * job.retry_count)
    await session.flush()
    return True
