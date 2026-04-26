import logging
import os

from pythonjsonlogger import jsonlogger

from .tracing_config import current_trace_context


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = current_trace_context()
        record.request_id = context.get('request_id')
        record.trace_id = context.get('trace_id')
        record.correlation_id = context.get('correlation_id')
        record.service = context.get('service')
        return True


def configure_logging(service_name: str) -> None:
    level = os.getenv('LOG_LEVEL', 'INFO').upper()
    fmt = os.getenv('LOG_FORMAT', 'json').lower()
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())
    if fmt == 'json':
        formatter = jsonlogger.JsonFormatter(
            '%(asctime)s %(levelname)s %(name)s %(service)s %(request_id)s %(trace_id)s %(correlation_id)s %(message)s'
        )
    else:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s [service=%(service)s request_id=%(request_id)s trace_id=%(trace_id)s correlation_id=%(correlation_id)s] %(message)s'
        )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    logging.getLogger(service_name).info('logging configured')
