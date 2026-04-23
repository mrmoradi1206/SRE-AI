import os
from pathlib import Path

SERVICE_NAME = 'report-agent'
HISTORY_AGENT_URL = os.getenv('HISTORY_AGENT_URL', 'http://history-agent:8001')
MATTERMOST_WEBHOOK_URL = os.getenv('MATTERMOST_WEBHOOK_URL', '')
TEAMS_WEBHOOK_URL = os.getenv('TEAMS_WEBHOOK_URL', '')
HTTP_MAX_RETRIES = int(os.getenv('HTTP_MAX_RETRIES', '3'))
HTTP_BASE_DELAY = float(os.getenv('HTTP_BASE_DELAY', '1.0'))
HTTP_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '30.0'))
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / 'templates' / 'report.md.j2'
