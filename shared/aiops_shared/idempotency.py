from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IncidentEvent


async def get_existing_event_by_idempotency(session: AsyncSession, idempotency_key: str | None) -> IncidentEvent | None:
    if not idempotency_key:
        return None
    return (
        await session.execute(
            select(IncidentEvent).where(IncidentEvent.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()


def ensure_idempotency_key(provided: str | None, prefix: str) -> str:
    return provided or f'{prefix}-{uuid4()}'
