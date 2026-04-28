from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LLMError(RuntimeError):
    provider: str
    model: str
    message: str
    status_code: int | None = None
    retryable: bool = False

    def __str__(self) -> str:
        suffix = f' status={self.status_code}' if self.status_code else ''
        return f'LLMError(provider={self.provider}, model={self.model}{suffix}): {self.message}'


def _provider_name(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == 'gateway':
        normalized = 'llmgateway'
    if normalized not in {'openrouter', 'llmgateway'}:
        raise LLMError(normalized or 'unknown', 'unknown', 'unsupported LLM provider')
    return normalized


def _api_key(provider: str) -> str | None:
    if provider == 'openrouter':
        return os.getenv('OPENROUTER_API_KEY') or os.getenv('AI_API_KEY')
    return os.getenv('LLM_GATEWAY_API_KEY') or os.getenv('SNAPP_LLM_API_KEY') or os.getenv('AI_API_KEY')


def _base_url(provider: str) -> str:
    if provider == 'openrouter':
        return os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/')
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


def _extract_content(data: dict[str, Any]) -> str:
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
    raise LLMError('unknown', 'unknown', 'LLM returned an empty completion')


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    if isinstance(exc, LLMError):
        return exc.retryable
    return False


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
        env_name = 'OPENROUTER_API_KEY' if selected_provider == 'openrouter' else 'LLM_GATEWAY_API_KEY'
        raise LLMError(selected_provider, selected_model, f'{env_name} is not configured')

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
    url = f'{_base_url(selected_provider)}/chat/completions'

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        for attempt in range(max(1, attempts)):
            try:
                logger.info('llm_call_started', extra={'provider': selected_provider, 'model': selected_model})
                response = await client.post(url, json=payload, headers=_headers(selected_provider, api_key))
                response.raise_for_status()
                data = response.json()
                content = _extract_content(data)
                logger.info('llm_call_completed', extra={'provider': selected_provider, 'model': selected_model})
                return {
                    'content': content,
                    'provider': selected_provider,
                    'model': selected_model,
                    'raw_response': data,
                }
            except httpx.HTTPStatusError as exc:
                last_error = exc
                retryable = _is_retryable(exc)
                if not retryable or attempt == attempts - 1:
                    raise LLMError(selected_provider, selected_model, 'provider HTTP error', exc.response.status_code, retryable) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise LLMError(selected_provider, selected_model, str(exc), retryable=True) from exc
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                raise LLMError(selected_provider, selected_model, 'unexpected LLM client error') from exc

            delay = min(backoff * (2 ** attempt), 8.0) + random.random() * 0.1
            await asyncio.sleep(delay)

    raise LLMError(selected_provider, selected_model, str(last_error or 'LLM request failed'), retryable=True)
