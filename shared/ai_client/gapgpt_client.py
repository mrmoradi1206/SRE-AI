from __future__ import annotations

from .openrouter_client import OpenRouterClient


class GapGPTClient(OpenRouterClient):
    provider_name = 'gapgpt'
