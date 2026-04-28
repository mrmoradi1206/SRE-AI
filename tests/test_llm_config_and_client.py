import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))

from aiops_shared.llm_config import get_agent_llm_config, load_llm_config, save_llm_config
from aiops_shared.llm_client import LLMError, run_llm


def test_dynamic_provider_switch(tmp_path, monkeypatch):
    path = tmp_path / 'llm_config.json'
    monkeypatch.setenv('LLM_CONFIG_PATH', str(path))

    saved = save_llm_config(
        {
            'providers': ['openrouter', 'llmgateway'],
            'models': {'openrouter': ['openai/gpt-4o-mini'], 'llmgateway': ['zai/glm-5.1']},
            'agents': {
                'supervisor': {'provider': 'openrouter', 'model': 'openai/gpt-4o-mini'},
                'report': {'provider': 'llmgateway', 'model': 'zai/glm-5.1'},
            },
        }
    )

    assert saved['agents']['supervisor']['provider'] == 'openrouter'
    assert get_agent_llm_config('report')['provider'] == 'llmgateway'


def test_dynamic_model_switch(tmp_path, monkeypatch):
    path = tmp_path / 'llm_config.json'
    monkeypatch.setenv('LLM_CONFIG_PATH', str(path))
    save_llm_config(
        {
            'providers': ['llmgateway'],
            'models': {'llmgateway': ['zai/glm-5.1', 'kimi/kimi-k2.5']},
            'agents': {
                'supervisor': {'provider': 'llmgateway', 'model': 'kimi/kimi-k2.5'},
                'report': {'provider': 'llmgateway', 'model': 'zai/glm-5.1'},
            },
        }
    )

    loaded = load_llm_config()
    assert loaded['agents']['supervisor']['model'] == 'kimi/kimi-k2.5'


@pytest.mark.asyncio
async def test_llm_retry_failover_behavior(monkeypatch):
    calls = {'count': 0}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'message': {'content': 'ok'}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            calls['count'] += 1
            if calls['count'] == 1:
                import httpx

                raise httpx.TransportError('temporary network failure')
            return FakeResponse()

    monkeypatch.setenv('OPENROUTER_API_KEY', 'secret')
    monkeypatch.setattr('aiops_shared.llm_client.httpx.AsyncClient', FakeClient)
    result = await run_llm('openrouter', 'openai/gpt-4o-mini', [{'role': 'user', 'content': 'ping'}], max_retries=2)

    assert calls['count'] == 2
    assert result['content'] == 'ok'
    assert result['provider'] == 'openrouter'


@pytest.mark.asyncio
async def test_llm_missing_key_raises_structured_error(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('AI_API_KEY', raising=False)

    with pytest.raises(LLMError) as exc:
        await run_llm('openrouter', 'openai/gpt-4o-mini', [{'role': 'user', 'content': 'ping'}], max_retries=1)

    assert exc.value.provider == 'openrouter'
    assert 'OPENROUTER_API_KEY' in exc.value.message
