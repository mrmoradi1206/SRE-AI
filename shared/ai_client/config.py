from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ResolvedAiSettings:
    provider: str
    model: str
    api_key: str | None
    base_url: str
    api_style: str = 'openai'
    timeout: float = 15.0
    default_headers: dict[str, str] = field(default_factory=dict)


def _extra_config(settings: Any | None) -> dict[str, Any]:
    extra = getattr(settings, 'extra_config', {}) if settings is not None else {}
    return extra if isinstance(extra, dict) else {}


def resolve_settings_for_agent(agent_name: str, settings: Any | None = None) -> ResolvedAiSettings:
    extra_config = _extra_config(settings)
    provider = str(
        extra_config.get('provider')
        or getattr(settings, 'provider', None)
        or os.getenv('AI_PROVIDER', 'openrouter')
    ).strip().lower()

    timeout = float(extra_config.get('timeout') or os.getenv('AI_CLIENT_TIMEOUT', '15'))

    if provider in {'gateway', 'llmgateway'}:
        api_style = str(extra_config.get('api_style') or os.getenv('SNAPP_LLM_API_STYLE', 'openai')).strip().lower()
        base_url = str(
            extra_config.get('base_url')
            or (
                os.getenv('SNAPP_LLM_ANTHROPIC_BASE', 'https://llm.snapp.tech/anthropic')
                if api_style == 'anthropic'
                else os.getenv('SNAPP_LLM_BASE_URL', 'https://llm.snapp.tech/v1')
            )
        )
        api_key = getattr(settings, 'api_key', None) or os.getenv('SNAPP_LLM_API_KEY') or os.getenv('AI_API_KEY')
        default_model = 'anthropic/claude-3-5-sonnet' if api_style == 'anthropic' else 'openai/gpt-4o-mini'
        model = str(extra_config.get('model') or getattr(settings, 'model', None) or os.getenv('AI_MODEL', default_model))
        headers = {'X-Agent-Name': agent_name}
        return ResolvedAiSettings(
            provider='llmgateway',
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip('/'),
            api_style=api_style,
            timeout=timeout,
            default_headers=headers,
        )

    if provider == 'gapgpt':
        base_url = str(extra_config.get('base_url') or os.getenv('GAPGPT_BASE_URL', 'https://api.gapgpt.app/v1'))
        api_key = getattr(settings, 'api_key', None) or os.getenv('GAPGPT_API_KEY') or os.getenv('AI_API_KEY')
        model = str(extra_config.get('model') or getattr(settings, 'model', None) or os.getenv('GAPGPT_DEFAULT_MODEL', 'gapgpt-qwen-3.5'))
        return ResolvedAiSettings(
            provider='gapgpt',
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip('/'),
            api_style='openai',
            timeout=timeout,
            default_headers={'X-Agent-Name': agent_name},
        )

    base_url = str(extra_config.get('base_url') or os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'))
    api_key = getattr(settings, 'api_key', None) or os.getenv('OPENROUTER_API_KEY') or os.getenv('AI_API_KEY')
    model = str(extra_config.get('model') or getattr(settings, 'model', None) or os.getenv('AI_MODEL', 'openai/gpt-4o-mini'))
    headers = {
        'HTTP-Referer': os.getenv('OPENROUTER_APP_URL', 'https://sre-ai.local'),
        'X-Title': os.getenv('OPENROUTER_APP_NAME', 'sre-ai'),
        'X-Agent-Name': agent_name,
    }
    return ResolvedAiSettings(
        provider='openrouter',
        model=model,
        api_key=api_key,
        base_url=base_url.rstrip('/'),
        api_style='openai',
        timeout=timeout,
        default_headers=headers,
    )
