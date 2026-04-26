from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))

from ai_client import GatewayClient, OpenRouterClient, resolve_client_for_agent
from ai_client.config import resolve_settings_for_agent


class FakeSettings:
    def __init__(self, provider='openrouter', model='demo-model', api_key='secret', extra_config=None):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.extra_config = extra_config or {}


def test_resolve_openrouter_client(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'or-key')
    settings = resolve_settings_for_agent('supervisor-agent', FakeSettings(provider='openrouter'))
    client = resolve_client_for_agent('supervisor-agent', FakeSettings(provider='openrouter'))
    assert settings.provider == 'openrouter'
    assert settings.api_key == 'or-key' or settings.api_key == 'secret'
    assert isinstance(client, OpenRouterClient)


def test_resolve_gateway_client(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'gateway')
    monkeypatch.setenv('SNAPP_LLM_API_KEY', 'gw-key')
    settings = resolve_settings_for_agent('report-agent', FakeSettings(provider='gateway', extra_config={'api_style': 'anthropic'}))
    client = resolve_client_for_agent('report-agent', FakeSettings(provider='gateway', extra_config={'api_style': 'anthropic'}))
    assert settings.provider == 'gateway'
    assert settings.api_style == 'anthropic'
    assert isinstance(client, GatewayClient)
