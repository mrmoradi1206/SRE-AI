from .base import AIClientError, AICompletionRequest, AICompletionResponse, AIMessage, BaseAIClient
from .config import ResolvedAiSettings, resolve_settings_for_agent
from .gapgpt_client import GapGPTClient
from .gateway_client import GatewayClient
from .openrouter_client import OpenRouterClient


def resolve_client_for_agent(agent_name: str, settings=None, client=None) -> BaseAIClient:
    resolved = resolve_settings_for_agent(agent_name, settings=settings)
    if resolved.provider in {'gateway', 'llmgateway'}:
        return GatewayClient(resolved, client=client)
    if resolved.provider == 'gapgpt':
        return GapGPTClient(resolved, client=client)
    return OpenRouterClient(resolved, client=client)


__all__ = [
    'AIClientError',
    'AICompletionRequest',
    'AICompletionResponse',
    'AIMessage',
    'BaseAIClient',
    'GapGPTClient',
    'GatewayClient',
    'OpenRouterClient',
    'ResolvedAiSettings',
    'resolve_client_for_agent',
    'resolve_settings_for_agent',
]
