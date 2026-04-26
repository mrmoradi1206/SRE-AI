import os
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import context as otel_context, propagate, trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .metrics import REQUEST_COUNT, REQUEST_ERRORS, REQUEST_IN_FLIGHT, REQUEST_LATENCY

request_id_ctx: ContextVar[str] = ContextVar('request_id', default='')
trace_id_ctx: ContextVar[str] = ContextVar('trace_id', default='')
correlation_id_ctx: ContextVar[str] = ContextVar('correlation_id', default='')
service_name_ctx: ContextVar[str] = ContextVar('service_name', default='')
_request_window_counts: dict[tuple[str, str], tuple[float, int]] = {}


def current_trace_context() -> dict[str, str]:
    return {
        'request_id': request_id_ctx.get(),
        'trace_id': trace_id_ctx.get(),
        'correlation_id': correlation_id_ctx.get(),
        'service': service_name_ctx.get(),
    }


def configure_tracing(service_name: str) -> None:
    if getattr(configure_tracing, '_configured', False):
        return
    provider = TracerProvider(resource=Resource.create({'service.name': service_name}))
    jaeger_host = os.getenv('JAEGER_HOST', 'jaeger')
    jaeger_port = int(os.getenv('JAEGER_PORT', '6831'))
    exporter = JaegerExporter(agent_host_name=jaeger_host, agent_port=jaeger_port)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    configure_tracing._configured = True


def instrument_app(app: FastAPI, service_name: str) -> None:
    service_name_ctx.set(service_name)
    configure_tracing(service_name)
    tracer = trace.get_tracer(service_name)
    rate_limit_per_minute = int(os.getenv('RATE_LIMIT_PER_MINUTE', '300'))

    @app.middleware('http')
    async def metrics_and_context_middleware(request: Request, call_next: Callable):
        carrier = dict(request.headers)
        parent_context = propagate.extract(carrier)
        token = otel_context.attach(parent_context)
        request_id = request.headers.get('X-Request-Id', str(uuid.uuid4()))
        correlation_id = request.headers.get('X-Correlation-Id', request_id)
        with tracer.start_as_current_span(f'{request.method} {request.url.path}') as span:
            trace_id = format(span.get_span_context().trace_id, '032x')
            span.set_attribute('http.method', request.method)
            span.set_attribute('http.target', request.url.path)
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
                    otel_context.detach(token)
                    return JSONResponse(
                        status_code=429,
                        content={'detail': 'rate limit exceeded', 'service': service_name, 'request_id': request_id, 'trace_id': trace_id, 'correlation_id': correlation_id},
                        headers={'Retry-After': '60'},
                    )

            start = time.perf_counter()
            path = request.url.path
            REQUEST_IN_FLIGHT.labels(service_name).inc()
            try:
                response = await call_next(request)
            except Exception:
                duration = time.perf_counter() - start
                REQUEST_COUNT.labels(service_name, request.method, path, '500').inc()
                REQUEST_LATENCY.labels(service_name, request.method, path).observe(duration)
                REQUEST_ERRORS.labels(service_name, request.method, path, '500').inc()
                span.record_exception(Exception('unhandled application error'))
                REQUEST_IN_FLIGHT.labels(service_name).dec()
                otel_context.detach(token)
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
            response.headers['traceparent'] = f'00-{trace_id}-0000000000000001-01'
            REQUEST_IN_FLIGHT.labels(service_name).dec()
            otel_context.detach(token)
            return response
