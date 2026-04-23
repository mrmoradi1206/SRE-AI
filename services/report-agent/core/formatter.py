from jinja2 import Template

from .config import TEMPLATE_PATH


class ReportFormatter:
    def __init__(self) -> None:
        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as handle:
            self.template = Template(handle.read())

    def render(self, context: dict) -> str:
        return self.template.render(**context)
