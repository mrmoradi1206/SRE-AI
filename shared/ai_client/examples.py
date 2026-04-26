from __future__ import annotations

from .base import AICompletionRequest, AIMessage
from .config import resolve_settings_for_agent
from .gateway_client import GatewayClient
from .openrouter_client import OpenRouterClient


async def openrouter_example() -> str:
    settings = resolve_settings_for_agent('example-openrouter')
    client = OpenRouterClient(settings)
    response = await client.complete(
        AICompletionRequest(
            model=settings.model,
            messages=[
                AIMessage(role='system', content='You are a concise SRE assistant.'),
                AIMessage(role='user', content='Summarize the probable cause of repeated HTTP 500 alerts.'),
            ],
            max_tokens=200,
        )
    )
    return response.content


async def snapp_gateway_example(api_style: str = 'openai') -> str:
    settings = resolve_settings_for_agent('example-gateway', settings=type('Settings', (), {'provider': 'gateway', 'extra_config': {'api_style': api_style}})())
    client = GatewayClient(settings)
    response = await client.complete(
        AICompletionRequest(
            model=settings.model,
            messages=[
                AIMessage(role='system', content='You are a concise incident commander assistant.'),
                AIMessage(role='user', content='Create three mitigation steps for a Redis saturation incident.'),
            ],
            max_tokens=200,
        )
    )
    return response.content
