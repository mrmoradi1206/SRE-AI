from __future__ import annotations

from typing import Any

import httpx

from .base import AIClientError, AICompletionRequest, AICompletionResponse, BaseAIClient
from .config import ResolvedAiSettings


class OpenRouterClient(BaseAIClient):
    provider_name = 'openrouter'

    def __init__(self, settings: ResolvedAiSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.timeout)

    async def complete(self, request: AICompletionRequest) -> AICompletionResponse:
        if not self.settings.api_key:
            raise AIClientError('OpenRouter API key is not configured')

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
            raise AIClientError('OpenRouter returned an empty completion')
        return AICompletionResponse(
            content=content,
            raw_response=data,
            provider=self.provider_name,
            model=payload['model'],
        )
