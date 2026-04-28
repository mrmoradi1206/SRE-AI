from __future__ import annotations

from typing import Any

import httpx

from .base import AIClientError, AICompletionRequest, AICompletionResponse, BaseAIClient
from .config import ResolvedAiSettings


class GatewayClient(BaseAIClient):
    provider_name = 'llmgateway'

    def __init__(self, settings: ResolvedAiSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.timeout)

    async def complete(self, request: AICompletionRequest) -> AICompletionResponse:
        if not self.settings.api_key:
            raise AIClientError('Snapp LLM Gateway API key is not configured')
        if self.settings.api_style == 'anthropic':
            return await self._complete_anthropic(request)
        return await self._complete_openai(request)

    async def _complete_openai(self, request: AICompletionRequest) -> AICompletionResponse:
        payload: dict[str, Any] = {
            'model': request.model or self.settings.model,
            'messages': [{'role': message.role, 'content': message.content} for message in request.messages],
            'temperature': request.temperature,
        }
        if request.max_tokens is not None:
            payload['max_tokens'] = request.max_tokens
        response = await self.client.post(
            f'{self.settings.base_url}/chat/completions',
            json=payload,
            headers={
                'Authorization': f'Bearer {self.settings.api_key}',
                **self.settings.default_headers,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = (((data.get('choices') or [{}])[0]).get('message') or {}).get('content')
        if not content:
            raise AIClientError('Snapp LLM Gateway returned an empty completion')
        return AICompletionResponse(content=content, raw_response=data, provider=self.provider_name, model=payload['model'])

    async def _complete_anthropic(self, request: AICompletionRequest) -> AICompletionResponse:
        system_prompt = next((message.content for message in request.messages if message.role == 'system'), '')
        user_content = '\n\n'.join(message.content for message in request.messages if message.role != 'system')
        payload: dict[str, Any] = {
            'model': request.model or self.settings.model,
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': user_content}],
            'temperature': request.temperature,
            'max_tokens': request.max_tokens or 512,
        }
        response = await self.client.post(
            f'{self.settings.base_url}/v1/messages',
            json=payload,
            headers={
                'x-api-key': self.settings.api_key,
                'anthropic-version': '2023-06-01',
                **self.settings.default_headers,
            },
        )
        response.raise_for_status()
        data = response.json()
        content_blocks = data.get('content') or []
        content = ''.join(block.get('text', '') for block in content_blocks if isinstance(block, dict))
        if not content:
            raise AIClientError('Anthropic-style gateway returned an empty completion')
        return AICompletionResponse(content=content, raw_response=data, provider=self.provider_name, model=payload['model'])
