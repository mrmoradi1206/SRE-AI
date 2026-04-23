import logging
import os
from datetime import datetime, timezone

from pythonjsonlogger import jsonlogger


def configure_logging(service_name: str) -> None:
    level = os.getenv('LOG_LEVEL', 'INFO').upper()
    fmt = os.getenv('LOG_FORMAT', 'json')
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler()
    if fmt == 'json':
        formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    else:
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)
    logging.getLogger(service_name).info('logging configured')


def health_payload(service: str, database: str = 'unknown') -> dict:
    return {
        'status': 'healthy',
        'service': service,
        'version': '1.0.0',
        'database': database,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
