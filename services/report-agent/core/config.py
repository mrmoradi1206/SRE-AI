import os

SERVICE_NAME = 'report-agent'
HISTORY_AGENT_URL = os.getenv('HISTORY_AGENT_URL', 'http://history-agent:8001')
HTTP_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '10'))
HTTP_MAX_RETRIES = int(os.getenv('HTTP_MAX_RETRIES', '3'))
HTTP_BACKOFF_SECONDS = float(os.getenv('HTTP_BACKOFF_SECONDS', '0.5'))
HTTP_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv('HTTP_CIRCUIT_BREAKER_THRESHOLD', '3'))
HTTP_CIRCUIT_BREAKER_RESET_SECONDS = float(os.getenv('HTTP_CIRCUIT_BREAKER_RESET_SECONDS', '30'))
AI_PROVIDER = os.getenv('AI_PROVIDER', 'stub')
AI_MODEL = os.getenv('AI_MODEL', 'local-fallback')
