from datetime import datetime, timezone
import logging
from pathlib import Path

from aiops_shared.context_loader import normalize_incident_bundle
from aiops_shared.llm_client import run_llm
from aiops_shared.llm_config import get_agent_system_prompt
from jinja2 import Template

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / 'templates' / 'report.md.j2'
logger = logging.getLogger(__name__)


class ReportFormatter:
    def __init__(self) -> None:
        self.template = Template(TEMPLATE_PATH.read_text(encoding='utf-8'))

    def render_template(self, incident_bundle: dict, provider: str, model: str) -> str:
        bundle = normalize_incident_bundle(incident_bundle)
        return self.template.render(
            incident=bundle['incident'],
            alerts=bundle.get('alerts', []),
            timeline=bundle.get('timeline', []),
            generated_at=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            model=model,
        )

    async def render_with_trace(self, incident_bundle: dict, provider: str, model: str) -> dict:
        baseline = self.render_template(incident_bundle, provider=provider, model=model)
        try:
            response = await run_llm(
                provider,
                model,
                [
                    {'role': 'system', 'content': get_agent_system_prompt('report')},
                    {'role': 'user', 'content': baseline},
                ],
                temperature=0.1,
                max_tokens=700,
            )
            return {'report': response['content'], 'fallback_used': False, 'llm_trace': response.get('trace')}
        except Exception as exc:  # noqa: BLE001
            logger.warning('report_llm_fallback_used', extra={'provider': provider, 'model': model, 'error_type': type(exc).__name__})
            return {
                'report': baseline,
                'fallback_used': True,
                'llm_trace': {'provider': provider, 'model': model, 'status': 'fallback', 'error': type(exc).__name__},
            }

    async def render(self, incident_bundle: dict, provider: str, model: str) -> str:
        return (await self.render_with_trace(incident_bundle, provider, model))['report']
