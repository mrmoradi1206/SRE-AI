from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': False,
    'webhook_url': '',
    'channel': '',
    'username': 'SRE-AI Report Agent',
    'icon_url': '',
}


class MattermostConfigError(ValueError):
    pass


class MattermostDeliveryError(RuntimeError):
    pass


def _repo_config_dir() -> Path | None:
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / 'config'
        if candidate.exists():
            return candidate
    return None


def mattermost_config_path() -> Path:
    configured = os.getenv('REPORT_INTEGRATIONS_CONFIG_PATH')
    if configured:
        return Path(configured)
    llm_config = os.getenv('LLM_CONFIG_PATH')
    if llm_config:
        return Path(llm_config).parent / 'report_integrations.json'
    config_dir = _repo_config_dir()
    return (config_dir / 'report_integrations.json') if config_dir else Path('/app/config/report_integrations.json')


def _clean_optional(value: Any, field: str, max_length: int = 200) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise MattermostConfigError(f'{field} must be a string')
    cleaned = value.strip()
    if len(cleaned) > max_length or any(ch in cleaned for ch in ['\n', '\r', '\x00']):
        raise MattermostConfigError(f'{field} is invalid')
    return cleaned


def _normalize_config(config: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise MattermostConfigError('config must be an object')
    base = {**DEFAULT_CONFIG, **(current or {})}
    enabled = bool(config.get('enabled', base['enabled']))
    webhook_url = _clean_optional(config.get('webhook_url', base.get('webhook_url')), 'webhook_url', max_length=2048)
    if webhook_url and not webhook_url.startswith(('http://', 'https://')):
        raise MattermostConfigError('webhook_url must start with http:// or https://')
    channel = _clean_optional(config.get('channel', base.get('channel')), 'channel')
    username = _clean_optional(config.get('username', base.get('username')), 'username') or DEFAULT_CONFIG['username']
    icon_url = _clean_optional(config.get('icon_url', base.get('icon_url')), 'icon_url', max_length=2048)
    if icon_url and not icon_url.startswith(('http://', 'https://')):
        raise MattermostConfigError('icon_url must start with http:// or https://')
    if enabled and not (webhook_url or os.getenv('MATTERMOST_WEBHOOK_URL')):
        raise MattermostConfigError('webhook_url is required when Mattermost delivery is enabled')
    return {
        'enabled': enabled,
        'webhook_url': webhook_url,
        'channel': channel,
        'username': username,
        'icon_url': icon_url,
    }


def load_mattermost_config() -> dict[str, Any]:
    path = mattermost_config_path()
    if not path.exists():
        return _normalize_config(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise MattermostConfigError(f'invalid JSON in {path}') from exc
    return _normalize_config(data)


def save_mattermost_config(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_mattermost_config()
    if not updates.get('webhook_url'):
        updates = {key: value for key, value in updates.items() if key != 'webhook_url'}
    normalized = _normalize_config(updates, current=current)
    path = mattermost_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as tmp:
        json.dump(normalized, tmp, indent=2)
        tmp.write('\n')
        tmp_path = Path(tmp.name)
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    return normalized


def public_mattermost_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    data = load_mattermost_config() if config is None else config
    webhook_url = data.get('webhook_url') or os.getenv('MATTERMOST_WEBHOOK_URL', '')
    return {
        'enabled': bool(data.get('enabled')),
        'webhook_url_configured': bool(webhook_url),
        'webhook_url_preview': _preview_url(webhook_url),
        'channel': data.get('channel') or '',
        'username': data.get('username') or DEFAULT_CONFIG['username'],
        'icon_url': data.get('icon_url') or '',
    }


def _preview_url(url: str) -> str:
    if not url:
        return ''
    if len(url) <= 28:
        return 'configured'
    return f'{url[:18]}...{url[-8:]}'


def build_mattermost_payload(report_text: str, incident_bundle: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    incident = incident_bundle.get('incident') or {}
    title = incident.get('summary') or incident.get('fingerprint') or incident.get('id') or 'incident report'
    text = f'### SRE-AI Incident Report: {title}\n\n{report_text}'
    payload: dict[str, Any] = {'text': text}
    if config.get('channel'):
        payload['channel'] = config['channel']
    if config.get('username'):
        payload['username'] = config['username']
    if config.get('icon_url'):
        payload['icon_url'] = config['icon_url']
    return payload


async def send_report_to_mattermost(report_text: str, incident_bundle: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    config = load_mattermost_config()
    if not config.get('enabled'):
        return {'enabled': False, 'sent': False, 'skipped': 'disabled'}
    webhook_url = config.get('webhook_url') or os.getenv('MATTERMOST_WEBHOOK_URL')
    if not webhook_url:
        raise MattermostDeliveryError('Mattermost webhook URL is not configured')
    payload = build_mattermost_payload(report_text, incident_bundle, config)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(webhook_url, json=payload)
    if response.status_code >= 400:
        detail = response.text[:300]
        channel_hint = ''
        if config.get('channel') and ('channel.app_error' in detail or response.status_code == 404):
            channel_hint = ' Channel override must be a channel name such as town-square, not a channel ID; leave it blank to use the webhook default channel.'
        raise MattermostDeliveryError(f'Mattermost returned HTTP {response.status_code}: {detail}{channel_hint}')
    return {'enabled': True, 'sent': True, 'status_code': response.status_code, 'channel': config.get('channel') or None}
