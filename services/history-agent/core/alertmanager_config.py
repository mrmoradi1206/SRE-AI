from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import (
    ALERTMANAGER_POLL_CONFIG_PATH,
    ALERTMANAGER_POLL_ENABLED,
    ALERTMANAGER_POLL_INTERVAL_SECONDS,
    ALERTMANAGER_POLL_PROXY_URL,
    ALERTMANAGER_POLL_TIMEOUT_SECONDS,
    ALERTMANAGER_POLL_VERIFY_TLS,
    ALERTMANAGER_URL,
)

DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': ALERTMANAGER_POLL_ENABLED,
    'url': ALERTMANAGER_URL,
    'interval_seconds': ALERTMANAGER_POLL_INTERVAL_SECONDS,
    'timeout_seconds': ALERTMANAGER_POLL_TIMEOUT_SECONDS,
    'verify_tls': ALERTMANAGER_POLL_VERIFY_TLS,
    'proxy_url': ALERTMANAGER_POLL_PROXY_URL,
}


class AlertmanagerConfigError(ValueError):
    pass


def _clean_url(value: Any, field: str) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise AlertmanagerConfigError(f'{field} must be a string')
    cleaned = value.strip().rstrip('/')
    if len(cleaned) > 500 or any(ch in cleaned for ch in ['\n', '\r', '\x00']):
        raise AlertmanagerConfigError(f'{field} is invalid')
    if cleaned and not cleaned.startswith(('http://', 'https://')):
        raise AlertmanagerConfigError(f'{field} must start with http:// or https://')
    return cleaned


def _normalize_config(config: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise AlertmanagerConfigError('config must be an object')
    base = {**DEFAULT_CONFIG, **(current or {})}
    interval = int(config.get('interval_seconds', base['interval_seconds']))
    timeout = float(config.get('timeout_seconds', base['timeout_seconds']))
    return {
        'enabled': bool(config.get('enabled', base['enabled'])),
        'url': _clean_url(config.get('url', base['url']), 'url') or DEFAULT_CONFIG['url'],
        'interval_seconds': max(5, min(interval, 300)),
        'timeout_seconds': max(1.0, min(timeout, 60.0)),
        'verify_tls': bool(config.get('verify_tls', base['verify_tls'])),
        'proxy_url': _clean_url(config.get('proxy_url', base['proxy_url']), 'proxy_url'),
    }


def alertmanager_config_path() -> Path:
    return Path(ALERTMANAGER_POLL_CONFIG_PATH)


def load_alertmanager_poll_config() -> dict[str, Any]:
    path = alertmanager_config_path()
    if not path.exists():
        return _normalize_config(DEFAULT_CONFIG)
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return _normalize_config(saved)


def save_alertmanager_poll_config(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_alertmanager_poll_config()
    normalized = _normalize_config(updates, current=current)
    path = alertmanager_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix('.tmp')
    tmp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tmp_path.replace(path)
    return normalized
