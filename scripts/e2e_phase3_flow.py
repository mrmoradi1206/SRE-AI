#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_URL = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8080'


def request(method: str, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f'{BASE_URL}{path}',
        data=data,
        method=method,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode('utf-8')
        return json.loads(body) if body else {}


def main() -> int:
    stamp = int(time.time())
    alert = {
        'source': 'phase3-e2e',
        'severity': 'critical',
        'summary': f'Phase 3 RAG learning smoke {stamp}',
        'labels': {'alertname': 'Phase3RAGSmoke', 'severity': 'critical', 'service': 'checkout', 'instance': f'e2e-{stamp}'},
        'annotations': {'description': 'Synthetic incident for approve-and-learn verification.'},
        'startsAt': datetime.now(timezone.utc).isoformat(),
    }
    ingestion = request('POST', '/api/history/alerts', alert)
    incident_id = ingestion['incident_id']
    print(f'incident_id={incident_id}')

    request('POST', '/api/supervisor/analyze', {'incident_id': incident_id, 'reasoning_mode': 'balanced'}, timeout=120)
    trace = request('GET', f'/api/supervisor/incidents/{incident_id}/trace')
    print(f'trace_steps={trace.get("count", 0)}')

    approval = request('POST', f'/api/supervisor/incidents/{incident_id}/approve', {
        'summary': alert['summary'],
        'root_cause': 'Synthetic checkout latency regression validated by phase3 e2e.',
        'resolution': 'Recorded operator-approved resolution for pgvector RAG retrieval testing.',
        'service': 'checkout',
        'severity': 'critical',
    })
    print(f'knowledge_id={approval["knowledge"]["id"]}')

    similar = request('GET', f'/api/supervisor/incidents/{incident_id}/similar')
    print(f'similar_count={similar.get("count", 0)}')
    assert approval.get('saved') is True
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode('utf-8'), file=sys.stderr)
        raise
