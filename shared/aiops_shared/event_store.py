from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IncidentEvent


async def next_sequence_number(session: AsyncSession, stream_id: UUID) -> int:
    max_sequence = await session.scalar(
        select(func.max(IncidentEvent.sequence_number)).where(IncidentEvent.stream_id == stream_id)
    )
    return int(max_sequence or 0) + 1


async def append_event(
    session: AsyncSession,
    *,
    stream_id: UUID,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    event_version: int = 1,
    causation_id: UUID | None = None,
    correlation_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        stream_id=stream_id,
        sequence_number=await next_sequence_number(session, stream_id),
        event_version=event_version,
        event_type=event_type,
        actor=actor,
        causation_id=causation_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload=payload,
        metadata=metadata or {},
    )
    session.add(event)
    await session.flush()
    return event
