from __future__ import annotations

import os
from typing import Any

import httpx

PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')


async def query_prometheus(query: str, time: str | None = None, prometheus_url: str | None = None) -> dict[str, Any]:
    params: dict[str, str] = {'query': query}
    if time:
        params['time'] = time
    base_url = (prometheus_url or PROMETHEUS_URL).rstrip('/')
    url = f'{base_url}/api/v1/query'
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()
