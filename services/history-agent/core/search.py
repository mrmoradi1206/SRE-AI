from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.models import Alert, Incident, IncidentEvent
from aiops_shared.utils import utcnow


async def build_incident_detail(
    session: AsyncSession,
    incident: Incident,
    alert_limit: int,
    alert_offset: int,
    *,
    timeline_limit: int = 200,
) -> dict:
    alerts = (
        await session.execute(
            select(Alert)
            .where(Alert.incident_id == incident.id)
            .order_by(Alert.created_at.desc())
            .offset(alert_offset)
            .limit(alert_limit)
        )
    ).scalars().all()
    timeline = (
        await session.execute(
            select(IncidentEvent)
            .where(IncidentEvent.stream_id == incident.id)
            .order_by(IncidentEvent.sequence_number.asc())
            .limit(timeline_limit)
        )
    ).scalars().all()
    return {'alerts': alerts, 'timeline': timeline}


def apply_incident_filters(
    stmt,
    status: str | None,
    fingerprint: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    *,
    query: str | None = None,
):
    filters = []
    if status:
        filters.append(Incident.status == status)
    if fingerprint:
        filters.append(Incident.fingerprint == fingerprint)
    if created_from:
        filters.append(Incident.created_at >= created_from)
    if created_to:
        filters.append(Incident.created_at <= created_to)
    if query:
        like_term = f'%{query.strip()}%'
        filters.append(
            or_(
                Incident.fingerprint.ilike(like_term),
                Incident.grouping_key.ilike(like_term),
                Incident.dedup_key.ilike(like_term),
                Incident.summary.ilike(like_term),
            )
        )
    if filters:
        stmt = stmt.where(and_(*filters))
    return stmt


def build_recent_alerts_stmt(*, hours: int, limit: int):
    cutoff = utcnow() - timedelta(hours=hours)
    return (
        select(Alert)
        .where(Alert.created_at >= cutoff)
        .order_by(Alert.created_at.desc())
        .limit(limit)
    )
