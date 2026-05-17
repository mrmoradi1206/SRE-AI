from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.getenv('OBSERVABILITY_INTEGRATIONS_CONFIG_PATH', '/app/config/observability_integrations.json'))
DEFAULT_CONFIG: dict[str, Any] = {
    'prometheus': {'url': os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')},
    'victoriametrics': {
        'url': os.getenv('VICTORIAMETRICS_URL', 'http://victoriametrics:8428'),
        'enabled': os.getenv('VICTORIAMETRICS_ENABLED', 'false').lower() == 'true',
    },
    'metrics_datasource': os.getenv('METRICS_DATASOURCE', 'prometheus'),
    'elasticsearch': {
        'enabled': os.getenv('ELASTICSEARCH_ENABLED', 'false').lower() == 'true',
        'url': os.getenv('ELASTICSEARCH_URL', 'http://elasticsearch:9200'),
        'index': os.getenv('ELASTICSEARCH_INDEX', 'logs-*'),
    },
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
    next_config = _merge(current, config)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix('.tmp')
    with tmp_path.open('w', encoding='utf-8') as handle:
        json.dump(next_config, handle, indent=2, sort_keys=True)
        handle.write('\n')
    tmp_path.replace(CONFIG_PATH)
    return next_config
