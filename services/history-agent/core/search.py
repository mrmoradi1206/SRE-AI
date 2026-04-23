from sqlalchemy.ext.asyncio import AsyncSession

from .storage import fetch_incident_context


async def search_by_fingerprint(session: AsyncSession, fingerprint: str, hours: int) -> dict | None:
    return await fetch_incident_context(session, fingerprint, hours)
