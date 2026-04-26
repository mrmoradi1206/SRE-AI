import os

SERVICE_NAME = 'history-agent'
MAX_PAGE_SIZE = min(int(os.getenv('MAX_PAGE_SIZE', '200')), 200)
DEFAULT_PAGE_SIZE = min(int(os.getenv('DEFAULT_PAGE_SIZE', '50')), 200)
DEFAULT_SLA_HOURS = int(os.getenv('DEFAULT_SLA_HOURS', '4'))
REOPEN_STALE_AFTER_HOURS = int(os.getenv('REOPEN_STALE_AFTER_HOURS', '24'))
DEFAULT_ALERT_CONTEXT_HOURS = int(os.getenv('DEFAULT_ALERT_CONTEXT_HOURS', '24'))
