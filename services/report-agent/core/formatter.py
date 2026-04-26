from datetime import datetime, timezone
from pathlib import Path

from ai_client import AICompletionRequest, AIMessage, resolve_client_for_agent
from jinja2 import Template

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / 'templates' / 'report.md.j2'


class ReportFormatter:
    def __init__(self) -> None:
        self.template = Template(TEMPLATE_PATH.read_text(encoding='utf-8'))

    def render_template(self, incident_bundle: dict, provider: str, model: str) -> str:
        return self.template.render(
            incident=incident_bundle['incident'],
            alerts=incident_bundle.get('alerts', []),
            timeline=incident_bundle.get('timeline', []),
            generated_at=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            model=model,
        )

    async def render(self, incident_bundle: dict, provider: str, model: str, settings=None) -> str:
        baseline = self.render_template(incident_bundle, provider=provider, model=model)
        try:
            client = resolve_client_for_agent('report-agent', settings=settings)
            response = await client.complete(
                AICompletionRequest(
                    model=model,
                    messages=[
                        AIMessage(role='system', content='Create a concise incident report in markdown.'),
                        AIMessage(role='user', content=baseline),
                    ],
                    max_tokens=700,
                )
            )
            return response.content
        except Exception:
            return baseline
