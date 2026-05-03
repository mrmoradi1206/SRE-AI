from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

ELASTICSEARCH_URL = os.getenv('ELASTICSEARCH_URL', 'http://elasticsearch:9200')
STACK_RE = re.compile(r'(?P<stack>(Traceback \(most recent call last\):.*|(?:\s+at\s+.*\n?){2,}))', re.DOTALL)


def _extract_stack_trace(message: str) -> str | None:
    match = STACK_RE.search(message or '')
    if not match:
        return None
    return match.group('stack')[:4000]


async def search_error_logs(service: str, minutes: int = 60, index: str = 'logs-*') -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(minutes=max(1, minutes))).isoformat()
    query = {
        'size': 10,
        'sort': [{'@timestamp': {'order': 'desc'}}],
        'query': {
            'bool': {
                'must': [
                    {'query_string': {'query': 'ERROR OR Exception OR Traceback'}},
                    {'range': {'@timestamp': {'gte': since}}},
                ],
                'filter': [{'term': {'service.name.keyword': service}}] if service else [],
            }
        },
    }
    url = f'{ELASTICSEARCH_URL.rstrip("/")}/{index}/_search'
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=query)
    response.raise_for_status()
    data = response.json()
    hits = data.get('hits', {}).get('hits', [])
    entries = []
    for hit in hits:
        source = hit.get('_source', {})
        message = source.get('message') or source.get('log', {}).get('message') or ''
        entries.append({
            'timestamp': source.get('@timestamp'),
            'service': source.get('service', {}).get('name') or source.get('service') or service,
            'message': message[:2000],
            'stack_trace': _extract_stack_trace(message),
            'index': hit.get('_index'),
        })
    return {'status': 'ok', 'service': service, 'minutes': minutes, 'entries': entries, 'raw_total': data.get('hits', {}).get('total')}
