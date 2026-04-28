from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
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


async def list_incidents_with_aggregates(
    session: AsyncSession,
    *,
    status: str | None = None,
    fingerprint: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Incident], dict[UUID, dict]]:
    """Fetch incidents with alert counts and latest event types in a single query."""
    base_stmt = apply_incident_filters(select(Incident), status, fingerprint, created_from, created_to, query=query)
    base_stmt = base_stmt.order_by(Incident.last_seen_at.desc()).offset(offset).limit(limit)

    incidents = (await session.execute(base_stmt)).scalars().all()
    if not incidents:
        return [], {}

    incident_ids = [incident.id for incident in incidents]

    # Aggregate alert counts per incident
    alert_count_stmt = (
        select(Alert.incident_id, func.count(Alert.id).label('alert_count'))
        .where(Alert.incident_id.in_(incident_ids))
        .group_by(Alert.incident_id)
    )
    alert_counts = {
        row.incident_id: row.alert_count
        for row in (await session.execute(alert_count_stmt)).mappings().all()
    }

    # Latest event type per incident using DISTINCT ON
    latest_event_stmt = (
        select(IncidentEvent.stream_id, IncidentEvent.event_type)
        .distinct(IncidentEvent.stream_id)
        .where(IncidentEvent.stream_id.in_(incident_ids))
        .order_by(IncidentEvent.stream_id, IncidentEvent.sequence_number.desc())
    )
    latest_events = {
        row.stream_id: row.event_type
        for row in (await session.execute(latest_event_stmt)).all()
    }

    aggregates = {
        iid: {
            'alert_count': alert_counts.get(iid, 0),
            'latest_event_type': latest_events.get(iid),
        }
        for iid in incident_ids
    }
    return list(incidents), aggregates


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
