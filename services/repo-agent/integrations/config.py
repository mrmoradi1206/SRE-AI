from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.getenv('REPO_INTEGRATIONS_CONFIG_PATH', '/app/config/repo_integrations.json'))
DEFAULT_CONFIG: dict[str, Any] = {
    'gitlab': {
        'url': os.getenv('GITLAB_URL', 'https://gitlab.com'),
        'token': os.getenv('GITLAB_TOKEN', ''),
        'default_project': os.getenv('GITLAB_PROJECT_ID', ''),
    }
}


def _merge(defaults: dict[str, Any], saved: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(defaults))
    for section, values in (saved or {}).items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update({key: value for key, value in values.items() if value is not None})
        else:
            merged[section] = values
    return merged


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with CONFIG_PATH.open('r', encoding='utf-8') as handle:
            saved = json.load(handle)
    except (OSError, json.JSONDecodeError):
        saved = {}
    return _merge(DEFAULT_CONFIG, saved)


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    incoming = json.loads(json.dumps(config))
    gitlab = incoming.get('gitlab')
    if isinstance(gitlab, dict) and gitlab.get('token') == '':
        gitlab.pop('token')
    next_config = _merge(current, incoming)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix('.tmp')
    with tmp_path.open('w', encoding='utf-8') as handle:
        json.dump(next_config, handle, indent=2, sort_keys=True)
        handle.write('\n')
    tmp_path.replace(CONFIG_PATH)
    return next_config


def public_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    gitlab = dict(config.get('gitlab') or {})
    token = gitlab.pop('token', '') or ''
    gitlab['token_configured'] = bool(token)
    gitlab['token_preview'] = f'{token[:4]}...{token[-4:]}' if len(token) >= 8 else ('configured' if token else '')
    return {'gitlab': gitlab}
