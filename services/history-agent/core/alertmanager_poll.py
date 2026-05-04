from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError

from aiops_shared.database import get_session_factory
from aiops_shared.schemas import AlertIn

from .alertmanager_config import load_alertmanager_poll_config
from .storage import ingest_alert, translate_integrity_error

logger = logging.getLogger(__name__)

_poll_task: asyncio.Task | None = None
_last_result: dict[str, Any] = {
    'running': False,
    'enabled': False,
    'url': '',
    'last_poll_at': None,
    'last_success_at': None,
    'last_error': None,
    'last_seen_alerts': 0,
    'last_ingested': 0,
    'duplicates': 0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _alert_event_key(alert: dict[str, Any]) -> str:
    labels = alert.get('labels') or {}
    fingerprint = alert.get('fingerprint') or ''
    starts_at = alert.get('startsAt') or alert.get('starts_at') or ''
    status = alert.get('status') or 'firing'
    label_key = '|'.join(f'{key}={labels[key]}' for key in sorted(labels))
    return f'alertmanager-poll:{fingerprint or label_key}:{starts_at}:{status}'


def _alert_summary(alert: dict[str, Any]) -> str:
    annotations = alert.get('annotations') or {}
    labels = alert.get('labels') or {}
    return annotations.get('summary') or annotations.get('description') or labels.get('alertname') or 'Alertmanager active alert'


def _alert_severity(alert: dict[str, Any]) -> str:
    labels = alert.get('labels') or {}
    return labels.get('severity') or labels.get('priority') or 'unknown'


def _alert_grouping_key(alert: dict[str, Any]) -> str:
    labels = alert.get('labels') or {}
    alertname = labels.get('alertname', 'unknown')
    service = labels.get('service') or labels.get('job') or labels.get('namespace') or labels.get('instance') or 'unknown'
    return f'alertmanager:{alertname}:{service}'


def _to_alert_in(alert: dict[str, Any]) -> AlertIn:
    status = (alert.get('status') or 'firing').lower()
    labels = alert.get('labels') or {}
    return AlertIn(
        event_key=_alert_event_key(alert),
        source='alertmanager-poll',
        severity=_alert_severity(alert),
        grouping_key=_alert_grouping_key(alert),
        summary=_alert_summary(alert),
        payload={
            **alert,
            'source': 'alertmanager-poll',
            'status': 'resolved' if status == 'resolved' else 'firing',
            'summary': _alert_summary(alert),
        },
        metadata={
            'actor': 'alertmanager-poller',
            'poll_source': 'alertmanager-api',
            'alertmanager_fingerprint': alert.get('fingerprint'),
            'labels': labels,
        },
    )


async def fetch_alertmanager_alerts(config: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"{config['url'].rstrip('/')}/api/v2/alerts"
    params = {'active': 'true', 'silenced': 'false', 'inhibited': 'false', 'unprocessed': 'true'}
    proxy_url = config.get('proxy_url') or None
    async with httpx.AsyncClient(
        timeout=float(config.get('timeout_seconds', 10)),
        verify=bool(config.get('verify_tls', True)),
        proxy=proxy_url,
    ) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, list) else []


async def poll_once() -> dict[str, Any]:
    config = load_alertmanager_poll_config()
    result = {
        'running': True,
        'enabled': bool(config.get('enabled')),
        'url': config.get('url') or '',
        'last_poll_at': _now_iso(),
        'last_success_at': _last_result.get('last_success_at'),
        'last_error': None,
        'last_seen_alerts': 0,
        'last_ingested': 0,
        'duplicates': 0,
    }
    if not config.get('enabled'):
        _last_result.update(result)
        return dict(_last_result)

    try:
        alerts = await fetch_alertmanager_alerts(config)
        result['last_seen_alerts'] = len(alerts)
        async with get_session_factory()() as session:
            for alert in alerts:
                try:
                    async with session.begin():
                        await ingest_alert(
                            session,
                            _to_alert_in(alert),
                            correlation_id=None,
                            idempotency_key=_alert_event_key(alert),
                            request_metadata={
                                'actor': 'alertmanager-poller',
                                'source_url': config.get('url'),
                                'poll_interval_seconds': config.get('interval_seconds'),
                            },
                        )
                    result['last_ingested'] += 1
                except IntegrityError as exc:
                    if translate_integrity_error(exc) in {'duplicate event_key', 'duplicate idempotency_key'}:
                        result['duplicates'] += 1
                        continue
                    raise
        result['last_success_at'] = _now_iso()
    except Exception as exc:
        result['last_error'] = f'{type(exc).__name__}: {exc}'
        logger.warning('alertmanager poll failed: %s', result['last_error'])
    _last_result.update(result)
    return dict(_last_result)


async def _poll_forever() -> None:
    while True:
        config = load_alertmanager_poll_config()
        await poll_once()
        await asyncio.sleep(int(config.get('interval_seconds', 10)))


async def start_alertmanager_poller() -> None:
    global _poll_task
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.create_task(_poll_forever(), name='alertmanager-poller')
        _last_result['running'] = True


async def stop_alertmanager_poller() -> None:
    global _poll_task
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    _poll_task = None
    _last_result['running'] = False


def poller_status() -> dict[str, Any]:
    config = load_alertmanager_poll_config()
    return {
        **_last_result,
        'running': bool(_poll_task and not _poll_task.done()),
        'enabled': bool(config.get('enabled')),
        'url': config.get('url') or '',
        'interval_seconds': config.get('interval_seconds'),
        'timeout_seconds': config.get('timeout_seconds'),
        'verify_tls': config.get('verify_tls'),
        'proxy_configured': bool(config.get('proxy_url')),
    }
