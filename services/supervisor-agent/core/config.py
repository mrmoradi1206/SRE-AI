import os
from pathlib import Path

SERVICE_NAME = 'supervisor-agent'
HISTORY_AGENT_URL = os.getenv('HISTORY_AGENT_URL', 'http://history-agent:8001')
REPORT_AGENT_URL = os.getenv('REPORT_AGENT_URL', 'http://report-agent:8002')
OBSERVABILITY_AGENT_URL = os.getenv('OBSERVABILITY_AGENT_URL', 'http://observability-agent:8003')
REPO_AGENT_URL = os.getenv('REPO_AGENT_URL', 'http://repo-agent:8004')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
REACT_MAX_ITERATIONS = int(os.getenv('REACT_MAX_ITERATIONS', '3'))
REACT_MEMORY_TTL_SECONDS = int(os.getenv('REACT_MEMORY_TTL_SECONDS', '86400'))
AI_PROVIDER = os.getenv('AI_PROVIDER', 'stub')
AI_MODEL = os.getenv('AI_MODEL', 'local-fallback')
AI_API_KEY = os.getenv('AI_API_KEY', '')
AI_EXTRA_CONFIG = os.getenv('AI_EXTRA_CONFIG', '{}')
HTTP_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '10'))
HTTP_MAX_RETRIES = int(os.getenv('HTTP_MAX_RETRIES', '3'))
HTTP_BACKOFF_SECONDS = float(os.getenv('HTTP_BACKOFF_SECONDS', '0.5'))
HTTP_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv('HTTP_CIRCUIT_BREAKER_THRESHOLD', '3'))
HTTP_CIRCUIT_BREAKER_RESET_SECONDS = float(os.getenv('HTTP_CIRCUIT_BREAKER_RESET_SECONDS', '30'))
PROMPT_PATH = Path(__file__).resolve().parent.parent / 'prompts' / 'default.yaml'
