from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .llm_config import LLMConfigError, get_provider_settings
from .metrics import LLM_CALLS, LLM_LATENCY
from .secret_store import SecretStoreError, get_runtime_secret

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LLMProviderError(Exception):
    provider: str
    model: str
    message: str
    status_code: int | None = None
    retryable: bool = False

    def __str__(self) -> str:
        suffix = f' status={self.status_code}' if self.status_code else ''
        return f'LLMError(provider={self.provider}, model={self.model}{suffix}): {self.message}'


class LLMError(LLMProviderError):
    pass


def _provider_name(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == 'gateway':
        normalized = 'llmgateway'
    if normalized not in {'openrouter', 'llmgateway', 'gapgpt'}:
        raise LLMError(normalized or 'unknown', 'unknown', 'unsupported LLM provider')
    return normalized


def _api_key_env(provider: str) -> str:
    try:
        return get_provider_settings(provider)['api_key_env']
    except LLMConfigError:
        if provider == 'openrouter':
            return 'OPENROUTER_API_KEY'
        if provider == 'gapgpt':
            return 'GAPGPT_API_KEY'
        return 'LLM_GATEWAY_API_KEY'


def _api_key(provider: str) -> str | None:
    configured_env = _api_key_env(provider)
    configured_key = os.getenv(configured_env)
    if configured_key:
        return configured_key
    try:
        runtime_key = get_runtime_secret(configured_env)
        if runtime_key:
            return runtime_key
    except SecretStoreError:
        logger.warning('runtime_secret_store_unavailable', extra={'provider': provider})
    if provider == 'openrouter':
        return os.getenv('OPENROUTER_API_KEY') or os.getenv('AI_API_KEY')
    if provider == 'gapgpt':
        return os.getenv('GAPGPT_API_KEY') or os.getenv('AI_API_KEY')
    return os.getenv('LLM_GATEWAY_API_KEY') or os.getenv('SNAPP_LLM_API_KEY') or os.getenv('AI_API_KEY')


def _base_url(provider: str) -> str:
    env_map = {
        'openrouter': 'OPENROUTER_BASE_URL',
        'gapgpt': 'GAPGPT_BASE_URL',
        'llmgateway': 'LLM_GATEWAY_BASE_URL',
    }
    if provider in env_map and os.getenv(env_map[provider]):
        return os.getenv(env_map[provider], '').rstrip('/')
    if provider == 'llmgateway' and os.getenv('SNAPP_LLM_BASE_URL'):
        return os.getenv('SNAPP_LLM_BASE_URL', '').rstrip('/')
    try:
        configured = get_provider_settings(provider).get('base_url')
        if configured:
            return configured.rstrip('/')
    except LLMConfigError:
        pass
    if provider == 'openrouter':
        return os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/')
    if provider == 'gapgpt':
        return os.getenv('GAPGPT_BASE_URL', 'https://api.gapgpt.app/v1').rstrip('/')
    return os.getenv('LLM_GATEWAY_BASE_URL') or os.getenv('SNAPP_LLM_BASE_URL', 'https://llm.snapp.tech/v1').rstrip('/')


def _headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'User-Agent': os.getenv('LLM_USER_AGENT', 'sre-ai/1.0'),
    }
    if provider == 'openrouter':
        headers['HTTP-Referer'] = os.getenv('OPENROUTER_APP_URL', 'https://sre-ai.local')
        headers['X-Title'] = os.getenv('OPENROUTER_APP_NAME', 'sre-ai')
    return headers


def _preview(value: Any, limit: int = 240) -> str:
    text = value if isinstance(value, str) else str(value)
    text = text.replace('\n', ' ').replace('\r', ' ')
    return text[:limit] + ('...' if len(text) > limit else '')


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            'role': str(message.get('role', 'unknown')),
            'content_preview': _preview(message.get('content', '')),
        }
        for message in messages[:12]
    ]


def _trace_payload(
    provider: str,
    model: str,
    payload: dict[str, Any],
    *,
    status: str,
    duration_ms: float,
    response_content: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    trace = {
        'provider': provider,
        'model': model,
        'status': status,
        'duration_ms': round(duration_ms, 2),
        'request': {
            'messages': _sanitize_messages(payload.get('messages', [])),
            'temperature': payload.get('temperature'),
            'max_tokens': payload.get('max_tokens'),
        },
    }
    if error:
        trace['error'] = _preview(error, limit=320)
    if response_content:
        trace['response'] = {'content_preview': _preview(response_content, limit=500)}
    return trace


def _extract_content(data: dict[str, Any], provider: str = 'unknown', model: str = 'unknown') -> str:
    choices = data.get('choices') or []
    if choices:
        message = choices[0].get('message') or {}
        content = message.get('content') or choices[0].get('text')
        if isinstance(content, str) and content.strip():
            return content
    content_blocks = data.get('content') or []
    if isinstance(content_blocks, list):
        content = ''.join(block.get('text', '') for block in content_blocks if isinstance(block, dict))
        if content.strip():
            return content
    raise LLMError(provider, model, 'LLM returned an empty completion')


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    if isinstance(exc, LLMError):
        return exc.retryable
    return False


async def _run_gapgpt(
    selected_provider: str,
    selected_model: str,
    api_key: str,
    payload: dict[str, Any],
    request_timeout: float,
) -> dict[str, Any]:
    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
    except ImportError as exc:
        raise LLMError(selected_provider, selected_model, 'openai package is not installed') from exc

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=_base_url(selected_provider), timeout=request_timeout)
        response = await client.chat.completions.create(**payload)
        content = response.choices[0].message.content if response.choices else None
        if not isinstance(content, str) or not content.strip():
            raise LLMError(selected_provider, selected_model, 'LLM returned an empty completion')
        raw_response = response.model_dump() if hasattr(response, 'model_dump') else response
        return {
            'content': content,
            'provider': selected_provider,
            'model': selected_model,
            'raw_response': raw_response,
        }
    except APIStatusError as exc:
        retryable = exc.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        raise LLMError(selected_provider, selected_model, 'provider HTTP error', exc.status_code, retryable) from exc
    except (APITimeoutError, APIConnectionError) as exc:
        raise LLMError(selected_provider, selected_model, str(exc), retryable=True) from exc


async def run_llm(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.1,
    *,
    max_tokens: int | None = 700,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Run a chat completion against the selected provider without logging secrets."""
    selected_provider = _provider_name(provider)
    selected_model = model.strip()
    if not selected_model:
        raise LLMError(selected_provider, selected_model, 'model is required')
    api_key = _api_key(selected_provider)
    if not api_key:
        raise LLMError(selected_provider, selected_model, f'{_api_key_env(selected_provider)} is not configured')

    payload: dict[str, Any] = {
        'model': selected_model,
        'messages': messages,
        'temperature': temperature,
    }
    if max_tokens is not None:
        payload['max_tokens'] = max_tokens

    request_timeout = timeout if timeout is not None else float(os.getenv('AI_CLIENT_TIMEOUT', '15'))
    attempts = max_retries if max_retries is not None else int(os.getenv('LLM_MAX_RETRIES', '3'))
    backoff = float(os.getenv('LLM_BACKOFF_SECONDS', '0.5'))
    max_backoff = float(os.getenv('LLM_MAX_BACKOFF_SECONDS', '8'))
    url = f'{_base_url(selected_provider)}/chat/completions'

    last_error: Exception | None = None
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        for attempt in range(max(1, attempts)):
            try:
                logger.info('llm_call_started', extra={'provider': selected_provider, 'model': selected_model})
                if selected_provider == 'gapgpt':
                    result = await _run_gapgpt(selected_provider, selected_model, api_key, payload, request_timeout)
                    duration = time.perf_counter() - started
                    result['trace'] = _trace_payload(
                        selected_provider,
                        selected_model,
                        payload,
                        status='ok',
                        duration_ms=duration * 1000,
                        response_content=result['content'],
                    )
                    LLM_CALLS.labels(selected_provider, selected_model, 'ok').inc()
                    LLM_LATENCY.labels(selected_provider, selected_model).observe(duration)
                    logger.info('llm_call_completed', extra={'provider': selected_provider, 'model': selected_model})
                    return result
                response = await client.post(url, json=payload, headers=_headers(selected_provider, api_key))
                response.raise_for_status()
                data = response.json()
                content = _extract_content(data, selected_provider, selected_model)
                duration = time.perf_counter() - started
                logger.info('llm_call_completed', extra={'provider': selected_provider, 'model': selected_model})
                LLM_CALLS.labels(selected_provider, selected_model, 'ok').inc()
                LLM_LATENCY.labels(selected_provider, selected_model).observe(duration)
                return {
                    'content': content,
                    'provider': selected_provider,
                    'model': selected_model,
                    'raw_response': data,
                    'trace': _trace_payload(
                        selected_provider,
                        selected_model,
                        payload,
                        status='ok',
                        duration_ms=duration * 1000,
                        response_content=content,
                    ),
                }
            except httpx.HTTPStatusError as exc:
                last_error = exc
                retryable = _is_retryable(exc)
                if not retryable or attempt == attempts - 1:
                    duration = time.perf_counter() - started
                    LLM_CALLS.labels(selected_provider, selected_model, 'error').inc()
                    LLM_LATENCY.labels(selected_provider, selected_model).observe(duration)
                    raise LLMError(selected_provider, selected_model, 'provider HTTP error', exc.response.status_code, retryable) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == attempts - 1:
                    duration = time.perf_counter() - started
                    LLM_CALLS.labels(selected_provider, selected_model, 'error').inc()
                    LLM_LATENCY.labels(selected_provider, selected_model).observe(duration)
                    raise LLMError(selected_provider, selected_model, str(exc), retryable=True) from exc
            except LLMError as exc:
                last_error = exc
                if not exc.retryable or attempt == attempts - 1:
                    duration = time.perf_counter() - started
                    LLM_CALLS.labels(selected_provider, selected_model, 'error').inc()
                    LLM_LATENCY.labels(selected_provider, selected_model).observe(duration)
                    raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                raise LLMError(selected_provider, selected_model, 'unexpected LLM client error') from exc

            delay = min(backoff * (2 ** attempt), max_backoff) + random.random() * 0.1
            await asyncio.sleep(delay)

    LLM_CALLS.labels(selected_provider, selected_model, 'error').inc()
    raise LLMError(selected_provider, selected_model, str(last_error or 'LLM request failed'), retryable=True)
