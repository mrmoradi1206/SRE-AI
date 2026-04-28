from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SECRET_NAME_RE = re.compile(r'^[A-Z][A-Z0-9_]{2,80}$')


class SecretStoreError(ValueError):
    pass


def _repo_config_dir() -> Path | None:
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / 'config'
        if candidate.exists():
            return candidate
    return None


def runtime_secrets_path() -> Path:
    configured = os.getenv('LLM_RUNTIME_SECRETS_PATH')
    if configured:
        return Path(configured)
    config_path = os.getenv('LLM_CONFIG_PATH')
    if config_path:
        return Path(config_path).parent / 'llm_runtime_secrets.json'
    config_dir = _repo_config_dir()
    return (config_dir / 'llm_runtime_secrets.json') if config_dir else Path('/app/config/llm_runtime_secrets.json')


def _validate_secret_name(name: str) -> str:
    cleaned = str(name).strip().upper()
    if not SECRET_NAME_RE.match(cleaned):
        raise SecretStoreError(f'invalid secret name: {name}')
    return cleaned


def load_runtime_secrets() -> dict[str, str]:
    path = runtime_secrets_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise SecretStoreError(f'invalid JSON in {path}') from exc
    if not isinstance(data, dict):
        raise SecretStoreError('runtime secrets must be an object')
    secrets: dict[str, str] = {}
    for key, value in data.items():
        name = _validate_secret_name(key)
        if isinstance(value, str) and value:
            secrets[name] = value
    return secrets


def get_runtime_secret(name: str) -> str | None:
    return load_runtime_secrets().get(_validate_secret_name(name))


def save_runtime_secrets(updates: dict[str, Any]) -> dict[str, bool]:
    current = load_runtime_secrets()
    for key, value in updates.items():
        name = _validate_secret_name(key)
        if value is None or value == '':
            continue
        if not isinstance(value, str):
            raise SecretStoreError(f'{name} must be a string')
        current[name] = value

    path = runtime_secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as tmp:
        json.dump(current, tmp, indent=2)
        tmp.write('\n')
        tmp_path = Path(tmp.name)
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    return {key: bool(value) for key, value in current.items()}
