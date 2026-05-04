from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_shared.database import get_db
from aiops_shared.dlq import enqueue_dead_letter
from aiops_shared.event_store import append_event
from aiops_shared.http_client import AsyncServiceClient
from aiops_shared.idempotency import ensure_idempotency_key, get_existing_event_by_idempotency
from aiops_shared.metrics import AGENT_ACTIONS
from aiops_shared.llm_config import get_agent_llm_config
from aiops_shared.models import Incident, IncidentEvent
from aiops_shared.schemas import ReportGenerateIn
from aiops_shared.utils import health_payload

from core.config import (
    HISTORY_AGENT_URL,
    HTTP_BACKOFF_SECONDS,
    HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    HTTP_CIRCUIT_BREAKER_THRESHOLD,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERVICE_NAME,
)
from core.formatter import ReportFormatter
from core.mattermost import (
    MattermostConfigError,
    MattermostDeliveryError,
    load_mattermost_config,
    public_mattermost_config,
    save_mattermost_config,
    send_report_to_mattermost,
)

router = APIRouter()
formatter = ReportFormatter()
http_client = AsyncServiceClient(
    timeout=HTTP_TIMEOUT,
    max_retries=HTTP_MAX_RETRIES,
    backoff_seconds=HTTP_BACKOFF_SECONDS,
    failure_threshold=HTTP_CIRCUIT_BREAKER_THRESHOLD,
    reset_timeout=HTTP_CIRCUIT_BREAKER_RESET_SECONDS,
    service_name=SERVICE_NAME,
)


def _metadata(request: Request) -> dict:
    return {
        'request_id': getattr(request.state, 'request_id', None),
        'trace_id': getattr(request.state, 'trace_id', None),
        'correlation_id': getattr(request.state, 'correlation_id', None),
        'path': str(request.url.path),
        'method': request.method,
    }


def _correlation_uuid(request: Request) -> UUID | None:
    raw = getattr(request.state, 'correlation_id', None)
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _event_agent(event: IncidentEvent) -> str:
    if event.event_type.startswith('history.'):
        return 'history-agent'
    if event.event_type.startswith('supervisor.'):
        return 'supervisor-agent'
    if event.event_type.startswith('report.'):
        return 'report-agent'
    return event.actor or 'unknown'


def _agent_action(event: IncidentEvent) -> str:
    payload = event.payload or {}
    if event.event_type in {'history.incident_opened', 'history.incident_reopened'}:
        return f"opened incident: {payload.get('summary') or payload.get('fingerprint') or 'no summary'}"
    if event.event_type == 'history.alert_attached':
        return f"attached alert {payload.get('event_key') or payload.get('alert_id') or ''}".strip()
    if event.event_type == 'history.incident_resolved':
        return payload.get('reason') or 'marked incident resolved from Alertmanager'
    if event.event_type == 'supervisor.status_changed':
        return f"changed status {payload.get('from')} -> {payload.get('to')}: {payload.get('reason') or 'no reason'}"
    if event.event_type in {'supervisor.action_recorded', 'supervisor.supervisor_action'}:
        decision = payload.get('decision') or (event.event_metadata or {}).get('reasoning_output', {}).get('next_state')
        root_cause = payload.get('root_cause') or (event.event_metadata or {}).get('reasoning_output', {}).get('root_cause')
        return f"analyzed incident; decision={decision or 'unknown'}; root_cause={root_cause or 'not provided'}"
    if event.event_type == 'report.report_generated':
        return f"generated final report with {payload.get('provider') or 'unknown'} / {payload.get('model') or 'unknown'}"
    if event.event_type == 'report.delivery_recorded':
        delivery = payload.get('delivery') or {}
        channel = payload.get('channel') or 'unknown'
        if delivery.get('sent'):
            target = f" ({delivery.get('channel')})" if delivery.get('channel') else ''
            return f'sent report to {channel}{target}'
        if delivery.get('skipped'):
            return f"skipped {channel} delivery: {delivery.get('skipped')}"
        return f"{channel} delivery failed: {delivery.get('error') or 'not sent'}"
    return event.event_type



def _compact_payload(event: IncidentEvent) -> dict:
    payload = event.payload or {}
    metadata = event.event_metadata or {}
    return {
        'payload': payload,
        'metadata': metadata,
        'llm_trace': payload.get('llm_trace') or metadata.get('reasoning_output', {}).get('llm_trace'),
        'react_trace': payload.get('react_trace') or metadata.get('reasoning_output', {}).get('react_trace') or [],
        'recommended_actions': payload.get('recommended_actions') or metadata.get('reasoning_output', {}).get('recommended_actions') or [],
        'root_cause': payload.get('root_cause') or metadata.get('reasoning_output', {}).get('root_cause'),
        'decision': payload.get('decision') or metadata.get('reasoning_output', {}).get('next_state'),
    }


def _agent_children_from_react(event: IncidentEvent) -> list[dict]:
    details = _compact_payload(event)
    children: list[dict] = []
    for index, step in enumerate(details.get('react_trace') or [], start=1):
        action = step.get('action') or {}
        observation = step.get('observation') or {}
        agent_response = observation.get('agent_response') if isinstance(observation, dict) else None
        source = observation.get('source') if isinstance(observation, dict) else None
        if agent_response:
            source = agent_response.get('agent') or source
        if source not in {'observability-agent', 'repo-agent'}:
            continue
        children.append({
            'sequence': f'{event.sequence_number}.{index}',
            'at': event.created_at,
            'agent': source,
            'event_type': f"tool.{action.get('name') or 'analyze'}",
            'action': agent_response.get('analysis') if isinstance(agent_response, dict) else observation.get('summary', 'agent returned evidence'),
            'status': agent_response.get('status') if isinstance(agent_response, dict) else observation.get('status'),
            'details': agent_response or observation,
        })
    return children

def _build_workflow_summary(incident_id: str, events: list[IncidentEvent]) -> dict:
    actions = []
    for event in events:
        details = _compact_payload(event)
        actions.append({
            'sequence': event.sequence_number,
            'at': event.created_at,
            'agent': _event_agent(event),
            'event_type': event.event_type,
            'action': _agent_action(event),
            'status': 'ok',
            'details': details,
        })
        actions.extend(_agent_children_from_react(event))
    report_events = [event for event in events if event.event_type == 'report.report_generated']
    delivery_events = [event for event in events if event.event_type == 'report.delivery_recorded']
    latest_report = report_events[-1].payload if report_events else None
    latest_delivery = delivery_events[-1].payload if delivery_events else None
    by_agent: dict[str, list[dict]] = {}
    for action in actions:
        by_agent.setdefault(action['agent'], []).append(action)
    commander_flow = {
        'brain': 'supervisor-agent',
        'contract': 'History records facts; observability-agent and repo-agent analyze evidence for Supervisor; report-agent writes the final report after Supervisor command.',
        'observability_reports_to_supervisor': any(action['agent'] == 'observability-agent' for action in actions),
        'repo_reports_to_supervisor': any(action['agent'] == 'repo-agent' for action in actions),
        'report_triggered_after_supervisor': bool(report_events) and any(event.event_type.startswith('supervisor.') for event in events),
    }
    lines = [f'# Cortex Workflow Report', '', f'Incident: `{incident_id}`', '', '## What Each Agent Did']
    for action in actions:
        lines.append(f"- {action['agent']} ({action['event_type']}): {action['action']}")
    lines.extend(['', '## Final Report'])
    lines.append(latest_report.get('report') if latest_report else 'No report has been generated yet.')
    lines.extend(['', '## Delivery'])
    if latest_delivery:
        delivery = latest_delivery.get('delivery') or {}
        lines.append(f"- Channel: {latest_delivery.get('channel') or 'unknown'}")
        lines.append(f"- Sent: {bool(delivery.get('sent'))}")
        if delivery.get('channel'):
            lines.append(f"- Target: {delivery.get('channel')}")
        if delivery.get('skipped'):
            lines.append(f"- Skipped: {delivery.get('skipped')}")
        if delivery.get('error'):
            lines.append(f"- Error: {delivery.get('error')}")
    else:
        lines.append('No channel delivery record exists for this incident yet.')
    return {
        'incident_id': incident_id,
        'actions': actions,
        'by_agent': by_agent,
        'commander_flow': commander_flow,
        'final_report': latest_report.get('report') if latest_report else None,
        'deliveries': [event.payload for event in delivery_events],
        'latest_delivery': latest_delivery,
        'markdown': '\n'.join(lines),
    }


@router.get('/health')
async def health(session: AsyncSession = Depends(get_db)) -> dict:
    database = 'connected'
    try:
        await session.execute(text('SELECT 1'))
    except Exception:
        database = 'disconnected'
    return health_payload(SERVICE_NAME, database, readiness=database)


@router.get('/ready')
async def ready(session: AsyncSession = Depends(get_db)) -> dict:
    try:
        await session.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='database unavailable') from exc
    return health_payload(SERVICE_NAME, 'connected', readiness='ready')


@router.get('/report/integrations/mattermost')
async def get_mattermost_integration() -> dict:
    try:
        return public_mattermost_config()
    except MattermostConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put('/report/integrations/mattermost')
async def update_mattermost_integration(payload: dict) -> dict:
    try:
        return public_mattermost_config(save_mattermost_config(payload))
    except MattermostConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail='failed to save Mattermost integration') from exc


@router.post('/report/integrations/mattermost/test')
async def test_mattermost_integration() -> dict:
    sample_bundle = {
        'incident': {
            'id': 'mattermost-test',
            'summary': 'Synthetic SRE-AI Mattermost delivery test',
            'severity': 'info',
            'status': 'testing',
        },
        'timeline': [],
        'alerts': [],
    }
    sample_report = (
        'This is a test message from the Cortex report-agent. '
        'If you can read this in Mattermost, report delivery is configured.'
    )
    try:
        return await send_report_to_mattermost(sample_report, sample_bundle, timeout=max(HTTP_TIMEOUT, 15.0))
    except MattermostConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MattermostDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post('/report/{incident_id}')
async def generate_report(
    incident_id: str,
    request: Request,
    payload: ReportGenerateIn | None = None,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    session: AsyncSession = Depends(get_db),
) -> dict:
    effective_idempotency_key = ensure_idempotency_key(idempotency_key, f'report:{incident_id}')
    async with session.begin():
        existing = await get_existing_event_by_idempotency(session, effective_idempotency_key)
        if existing is not None:
            return {'incident_id': incident_id, 'report': existing.payload.get('report'), 'deduplicated': True}

    try:
        response = await http_client.get(f'{HISTORY_AGENT_URL}/incidents/{incident_id}')
        incident_bundle = response.json()
    except Exception as exc:
        async with session.begin():
            await enqueue_dead_letter(
                session,
                service=SERVICE_NAME,
                operation='generate_report.fetch_incident',
                payload={'incident_id': incident_id},
                error_message=str(exc),
                correlation_id=_correlation_uuid(request),
                idempotency_key=effective_idempotency_key,
            )
        raise HTTPException(status_code=502, detail='failed to fetch incident context') from exc

    llm_settings = get_agent_llm_config('report')
    render_result = await formatter.render_with_trace(incident_bundle, provider=llm_settings['provider'], model=llm_settings['model'])
    report_text = render_result['report']

    try:
        async with session.begin():
            incident = (await session.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
            if incident is None:
                raise HTTPException(status_code=404, detail='incident not found')
            event = await append_event(
                session,
                stream_id=incident.id,
                event_type='report.report_generated',
                actor='report-agent',
                correlation_id=_correlation_uuid(request),
                idempotency_key=effective_idempotency_key,
                payload={
                    'report': report_text,
                    'provider': llm_settings['provider'],
                    'model': llm_settings['model'],
                    'analysis': payload.analysis if payload else None,
                    'fallback_used': render_result['fallback_used'],
                    'llm_trace': render_result.get('llm_trace'),
                },
                metadata=_metadata(request),
            )
    except IntegrityError:
        async with session.begin():
            existing = await get_existing_event_by_idempotency(session, effective_idempotency_key)
        if existing is not None:
            return {'incident_id': incident_id, 'report': existing.payload.get('report'), 'deduplicated': True}
        raise

    mattermost_delivery = {'enabled': False, 'sent': False, 'skipped': 'disabled'}
    try:
        mattermost_delivery = await send_report_to_mattermost(report_text, incident_bundle, timeout=max(HTTP_TIMEOUT, 15.0))
    except Exception as exc:  # noqa: BLE001
        mattermost_delivery = {'enabled': True, 'sent': False, 'error': str(exc)}
        async with session.begin():
            await enqueue_dead_letter(
                session,
                service=SERVICE_NAME,
                operation='report.deliver_mattermost',
                payload={'incident_id': incident_id, 'event_id': str(event.event_id)},
                error_message=str(exc),
                correlation_id=_correlation_uuid(request),
                idempotency_key=f'mattermost:{effective_idempotency_key}',
            )
    async with session.begin():
        await append_event(
            session,
            stream_id=event.stream_id,
            event_type='report.delivery_recorded',
            actor='report-agent',
            correlation_id=_correlation_uuid(request),
            idempotency_key=f'delivery:{effective_idempotency_key}',
            causation_id=event.event_id,
            payload={
                'report_event_id': str(event.event_id),
                'channel': 'mattermost',
                'delivery': mattermost_delivery,
            },
            metadata=_metadata(request),
        )
    AGENT_ACTIONS.labels('report-agent', 'report_generated').inc()
    return {
        'incident_id': incident_id,
        'report': report_text,
        'event_id': str(event.event_id),
        'provider': llm_settings['provider'],
        'model': llm_settings['model'],
        'fallback_used': render_result['fallback_used'],
        'llm_trace': render_result.get('llm_trace'),
        'mattermost_delivery': mattermost_delivery,
    }


@router.get('/report/{incident_id}')
async def get_latest_report(incident_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    event = (
        await session.execute(
            select(IncidentEvent)
            .where(IncidentEvent.stream_id == incident_id, IncidentEvent.event_type == 'report.report_generated')
            .order_by(IncidentEvent.sequence_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail='report not found')
    return {'incident_id': incident_id, 'report_event': event.payload, 'created_at': event.created_at, 'event_id': event.event_id}


@router.get('/report/{incident_id}/workflow-summary')
async def get_workflow_summary(incident_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    events = (
        await session.execute(
            select(IncidentEvent)
            .where(IncidentEvent.stream_id == incident_id)
            .order_by(IncidentEvent.sequence_number.asc())
        )
    ).scalars().all()
    if not events:
        raise HTTPException(status_code=404, detail='incident workflow not found')
    return _build_workflow_summary(incident_id, events)
