import os
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

request_id_ctx: ContextVar[str] = ContextVar('request_id', default='')
trace_id_ctx: ContextVar[str] = ContextVar('trace_id', default='')
correlation_id_ctx: ContextVar[str] = ContextVar('correlation_id', default='')
service_name_ctx: ContextVar[str] = ContextVar('service_name', default='')

REQUEST_COUNT = Counter('sre_ai_http_requests_total', 'HTTP request count', ['service', 'method', 'path', 'status'])
REQUEST_LATENCY = Histogram('sre_ai_http_request_duration_seconds', 'HTTP request latency', ['service', 'method', 'path'])
REQUEST_ERRORS = Counter('sre_ai_http_errors_total', 'HTTP errors', ['service', 'method', 'path', 'status'])
EXTERNAL_CALLS = Counter('sre_ai_external_calls_total', 'External or inter-service calls', ['service', 'target', 'method', 'status'])
DLQ_EVENTS = Counter('sre_ai_dlq_events_total', 'Dead letter queue enqueues', ['service', 'operation'])
_request_window_counts: dict[tuple[str, str], tuple[float, int]] = {}


def current_request_context() -> dict[str, str]:
    return {
        'request_id': request_id_ctx.get(),
        'trace_id': trace_id_ctx.get(),
        'correlation_id': correlation_id_ctx.get(),
        'service': service_name_ctx.get(),
    }


def instrument_app(app: FastAPI, service_name: str) -> None:
    service_name_ctx.set(service_name)
    rate_limit_per_minute = int(os.getenv('RATE_LIMIT_PER_MINUTE', '300'))

    @app.middleware('http')
    async def metrics_and_context_middleware(request: Request, call_next: Callable):
        request_id = request.headers.get('X-Request-Id', str(uuid.uuid4()))
        trace_id = request.headers.get('X-Trace-Id', request_id)
        correlation_id = request.headers.get('X-Correlation-Id', trace_id)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.correlation_id = correlation_id
        request_id_ctx.set(request_id)
        trace_id_ctx.set(trace_id)
        correlation_id_ctx.set(correlation_id)
        service_name_ctx.set(service_name)

        if rate_limit_per_minute > 0:
            client_ip = request.client.host if request.client else 'unknown'
            key = (service_name, client_ip)
            now = time.monotonic()
            window_start, count = _request_window_counts.get(key, (now, 0))
            if now - window_start >= 60:
                window_start, count = now, 0
            count += 1
            _request_window_counts[key] = (window_start, count)
            if count > rate_limit_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={
                        'detail': 'rate limit exceeded',
                        'service': service_name,
                        'request_id': request_id,
                        'trace_id': trace_id,
                        'correlation_id': correlation_id,
                    },
                    headers={'Retry-After': '60'},
                )

        start = time.perf_counter()
        path = request.url.path
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            REQUEST_COUNT.labels(service_name, request.method, path, '500').inc()
            REQUEST_LATENCY.labels(service_name, request.method, path).observe(duration)
            REQUEST_ERRORS.labels(service_name, request.method, path, '500').inc()
            raise

        duration = time.perf_counter() - start
        status = str(response.status_code)
        REQUEST_COUNT.labels(service_name, request.method, path, status).inc()
        REQUEST_LATENCY.labels(service_name, request.method, path).observe(duration)
        if response.status_code >= 500:
            REQUEST_ERRORS.labels(service_name, request.method, path, status).inc()
        response.headers['X-Request-Id'] = request_id
        response.headers['X-Trace-Id'] = trace_id
        response.headers['X-Correlation-Id'] = correlation_id
        return response


def metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get('/metrics', include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
