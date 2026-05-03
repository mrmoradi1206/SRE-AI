from __future__ import annotations

import os
from typing import Any

import httpx

PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')


async def query_prometheus(query: str, time: str | None = None) -> dict[str, Any]:
    params: dict[str, str] = {'query': query}
    if time:
        params['time'] = time
    url = f'{PROMETHEUS_URL.rstrip("/")}/api/v1/query'
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()
