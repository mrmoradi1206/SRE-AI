import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from opentelemetry import propagate

from .metrics import EXTERNAL_CALLS
from .tracing_config import current_trace_context


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.state = 'closed'
        self.opened_at = 0.0
        self.last_error: str | None = None

    def _can_attempt(self) -> bool:
        if self.state == 'closed':
            return True
        if self.state == 'open' and (time.monotonic() - self.opened_at) >= self.reset_timeout:
            self.state = 'half-open'
            return True
        return self.state == 'half-open'

    async def call(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        if not self._can_attempt():
            raise RuntimeError('circuit breaker is open')
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            self.failure_count += 1
            self.last_error = str(exc)
            if self.failure_count >= self.failure_threshold:
                self.state = 'open'
                self.opened_at = time.monotonic()
            raise
        self.failure_count = 0
        self.state = 'closed'
        self.last_error = None
        return result


class AsyncServiceClient:
    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 10.0,
        jitter_ratio: float = 0.2,
        failure_threshold: int = 3,
        reset_timeout: float = 30.0,
        enable_circuit_breaker: bool = True,
        service_name: str = 'unknown-service',
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.jitter_ratio = jitter_ratio
        self.service_name = service_name
        self.client = httpx.AsyncClient(timeout=timeout)
        self.breaker = CircuitBreaker(failure_threshold=failure_threshold, reset_timeout=reset_timeout)
        self.enable_circuit_breaker = enable_circuit_breaker

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _request_once(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        context = current_trace_context()
        headers = kwargs.pop('headers', {})
        headers = {
            'X-Request-Id': context.get('request_id') or '',
            'X-Trace-Id': context.get('trace_id') or '',
            'X-Correlation-Id': context.get('correlation_id') or '',
            **headers,
        }
        propagate.inject(headers)
        response = await self.client.request(method, url, headers=headers, **kwargs)
        target = url.split('/')[2] if '://' in url else url
        EXTERNAL_CALLS.labels(self.service_name, target, method.upper(), str(response.status_code)).inc()
        response.raise_for_status()
        return response

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def runner() -> httpx.Response:
            last_error: Exception | None = None
            for attempt in range(self.max_retries):
                try:
                    return await self._request_once(method, url, **kwargs)
                except (httpx.HTTPError, httpx.TimeoutException, RuntimeError) as exc:
                    last_error = exc
                    retryable = isinstance(exc, (httpx.TimeoutException, RuntimeError))
                    if isinstance(exc, httpx.HTTPStatusError):
                        retryable = exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
                    if not retryable:
                        raise
                    if attempt == self.max_retries - 1:
                        raise
                    delay = min(self.backoff_seconds * (2 ** attempt), self.max_backoff_seconds)
                    jitter = delay * self.jitter_ratio * random.random()
                    await asyncio.sleep(delay + jitter)
            if last_error is not None:
                raise last_error
            raise RuntimeError('request failed without a captured error')

        if self.enable_circuit_breaker:
            return await self.breaker.call(runner)
        return await runner()

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request('GET', url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request('POST', url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request('PUT', url, **kwargs)
