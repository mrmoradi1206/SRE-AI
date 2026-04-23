import asyncio
from collections.abc import Callable
from typing import Any

import httpx


class RetryableHTTPClient:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, timeout: float = 30.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.client = httpx.AsyncClient(timeout=timeout)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(self.base_delay * (2 ** attempt))
        raise last_error

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request('GET', url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request('POST', url, **kwargs)


class CircuitBreaker:
    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.failures = 0
        self.open = False

    async def call(self, func: Callable, *args: Any, **kwargs: Any):
        if self.open:
            raise RuntimeError('circuit breaker open')
        try:
            result = await func(*args, **kwargs)
            self.failures = 0
            return result
        except Exception:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open = True
            raise
