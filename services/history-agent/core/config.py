import os

SERVICE_NAME = 'history-agent'
SUPERVISOR_AGENT_URL = os.getenv('SUPERVISOR_AGENT_URL', 'http://supervisor-agent:8002')
HTTP_MAX_RETRIES = int(os.getenv('HTTP_MAX_RETRIES', '3'))
HTTP_BASE_DELAY = float(os.getenv('HTTP_BASE_DELAY', '1.0'))
HTTP_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '30.0'))
