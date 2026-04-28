from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

SUPPORTED_PROVIDERS = {'openrouter', 'llmgateway'}
KNOWN_AGENTS = {'supervisor', 'report'}

DEFAULT_LLM_CONFIG: dict[str, Any] = {
    'providers': ['openrouter', 'llmgateway'],
    'models': {
        'openrouter': ['meta-llama/llama-3.1-8b-instruct', 'qwen/qwen-2.5-72b-instruct', 'openai/gpt-4o-mini'],
        'llmgateway': ['zai/glm-5.1', 'zai/glm-5', 'minimax/MiniMax-M2.7', 'kimi/kimi-k2.5'],
    },
    'agents': {
        'supervisor': {'provider': 'llmgateway', 'model': 'zai/glm-5.1'},
        'report': {'provider': 'openrouter', 'model': 'meta-llama/llama-3.1-8b-instruct'},
    },
}


class LLMConfigError(ValueError):
    pass


def _repo_config_path() -> Path | None:
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / 'config' / 'llm_config.json'
        if candidate.exists():
            return candidate
    return None


def llm_config_path() -> Path:
    configured = os.getenv('LLM_CONFIG_PATH')
    if configured:
        return Path(configured)
    return _repo_config_path() or Path('/app/config/llm_config.json')


def _clean_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LLMConfigError(f'{field} must be a string')
    cleaned = value.strip().lower() if field.endswith('provider') else value.strip()
    if not cleaned or len(cleaned) > 160 or any(ch in cleaned for ch in ['\n', '\r', '\x00']):
        raise LLMConfigError(f'{field} is invalid')
    return cleaned


def validate_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise LLMConfigError('config must be an object')

    providers = [_clean_string(item, 'provider') for item in config.get('providers', [])]
    if not providers:
        raise LLMConfigError('at least one provider is required')
    unknown = set(providers) - SUPPORTED_PROVIDERS
    if unknown:
        raise LLMConfigError(f'unsupported providers: {", ".join(sorted(unknown))}')

    raw_models = config.get('models', {})
    if not isinstance(raw_models, dict):
        raise LLMConfigError('models must be an object')
    models: dict[str, list[str]] = {}
    for provider in providers:
        values = raw_models.get(provider, [])
        if not isinstance(values, list) or not values:
            raise LLMConfigError(f'models.{provider} must be a non-empty list')
        deduped = []
        for item in values:
            model = _clean_string(item, f'models.{provider}')
            if model not in deduped:
                deduped.append(model)
        models[provider] = deduped

    raw_agents = config.get('agents', {})
    if not isinstance(raw_agents, dict):
        raise LLMConfigError('agents must be an object')
    agents: dict[str, dict[str, str]] = {}
    for agent, raw_selection in raw_agents.items():
        agent_name = _clean_string(agent, 'agent')
        if agent_name not in KNOWN_AGENTS:
            raise LLMConfigError(f'unsupported agent: {agent_name}')
        if not isinstance(raw_selection, dict):
            raise LLMConfigError(f'agents.{agent_name} must be an object')
        provider = _clean_string(raw_selection.get('provider'), 'agent.provider')
        if provider not in providers:
            raise LLMConfigError(f'agents.{agent_name}.provider is not enabled')
        model = _clean_string(raw_selection.get('model'), f'agents.{agent_name}.model')
        if model not in models[provider]:
            raise LLMConfigError(f'agents.{agent_name}.model is not available for {provider}')
        agents[agent_name] = {'provider': provider, 'model': model}

    for agent in KNOWN_AGENTS:
        if agent not in agents:
            default = DEFAULT_LLM_CONFIG['agents'][agent]
            provider = default['provider'] if default['provider'] in providers else providers[0]
            model = default['model'] if default['model'] in models[provider] else models[provider][0]
            agents[agent] = {'provider': provider, 'model': model}

    return {'providers': providers, 'models': models, 'agents': agents}


def load_llm_config() -> dict[str, Any]:
    path = llm_config_path()
    if not path.exists():
        return validate_llm_config(deepcopy(DEFAULT_LLM_CONFIG))
    try:
        return validate_llm_config(json.loads(path.read_text(encoding='utf-8')))
    except json.JSONDecodeError as exc:
        raise LLMConfigError(f'invalid JSON in {path}') from exc


def save_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_llm_config(config)
    path = llm_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as tmp:
        json.dump(normalized, tmp, indent=2)
        tmp.write('\n')
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return normalized


def get_agent_llm_config(agent: str) -> dict[str, str]:
    config = load_llm_config()
    agent_name = _clean_string(agent, 'agent')
    if agent_name not in config['agents']:
        raise LLMConfigError(f'unsupported agent: {agent_name}')
    return dict(config['agents'][agent_name])
