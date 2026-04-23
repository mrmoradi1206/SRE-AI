import json
import logging

import yaml
from jinja2 import Template

from aiops_shared.http_client import CircuitBreaker, RetryableHTTPClient

from .config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL, PROMPT_PATH

logger = logging.getLogger(__name__)


class OpenRouterClient:
    def __init__(self, http_client: RetryableHTTPClient):
        self.http_client = http_client
        self.breaker = CircuitBreaker()
        with open(PROMPT_PATH, 'r', encoding='utf-8') as handle:
            self.prompt_config = yaml.safe_load(handle)

    def render_prompt(self, context: dict) -> list[dict]:
        system_prompt = self.prompt_config['system_prompt']
        user_prompt = Template(self.prompt_config['user_prompt_template']).render(**context)
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

    async def analyze(self, context: dict) -> dict:
        if not OPENROUTER_API_KEY:
            return fallback_analysis(context, 'OPENROUTER_API_KEY missing')

        async def _call() -> dict:
            payload = {
                'model': OPENROUTER_MODEL,
                'messages': self.render_prompt(context),
                'temperature': 0.3,
                'max_tokens': 2000,
                'response_format': {'type': 'json_object'},
            }
            response = await self.http_client.post(
                f'{OPENROUTER_BASE_URL}/chat/completions',
                json=payload,
                headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}'},
            )
            data = response.json()
            content = data['choices'][0]['message']['content']
            return json.loads(content)

        try:
            return await self.breaker.call(_call)
        except Exception as exc:
            logger.exception('llm analysis failed')
            return fallback_analysis(context, str(exc))


def fallback_analysis(context: dict, error: str) -> dict:
    current = context.get('current_alert') or {}
    labels = current.get('labels', {})
    alertname = labels.get('alertname', 'UnknownAlert')
    instance = labels.get('instance', 'unknown')
    return {
        'root_cause': f'{alertname} detected on {instance}',
        'diagnosis': 'LLM analysis unavailable. Manual investigation required using alert annotations and host telemetry.',
        'business_impact': 'Potential service degradation. Impact needs manual confirmation.',
        'is_recurring': len(context.get('historical_alerts', [])) > 1,
        'recurrence_note': 'Fallback mode used due to external analysis failure.',
        'recommendations': [
            {
                'priority': 1,
                'action': 'Inspect recent metrics and logs for the affected instance.',
                'rationale': 'Provides a safe first step while automated reasoning is unavailable.',
            }
        ],
        'severity': labels.get('severity', 'medium'),
        'confidence': 0.0,
        'error': error,
    }
