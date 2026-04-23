import os
from pathlib import Path

SERVICE_NAME = 'supervisor-agent'
HISTORY_AGENT_URL = os.getenv('HISTORY_AGENT_URL', 'http://history-agent:8001')
REPORT_AGENT_URL = os.getenv('REPORT_AGENT_URL', 'http://report-agent:8003')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'anthropic/claude-3.5-sonnet')
OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
HTTP_MAX_RETRIES = int(os.getenv('HTTP_MAX_RETRIES', '3'))
HTTP_BASE_DELAY = float(os.getenv('HTTP_BASE_DELAY', '1.0'))
HTTP_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '30.0'))
PROMPT_PATH = Path(__file__).resolve().parent.parent / 'prompts' / 'default.yaml'
