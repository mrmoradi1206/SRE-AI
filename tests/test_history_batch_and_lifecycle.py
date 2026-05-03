from datetime import timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
sys.path.insert(0, str(ROOT / 'services' / 'history-agent'))

from aiops_shared.models import IncidentStatus
from aiops_shared.schemas import AlertBatchIn, AlertIn
from aiops_shared.utils import utcnow
from core.storage import _payload_received_at, ingest_alert_batch, is_resolved_alert, recent_alerts_summary, should_reopen_incident


class FakeSession:
    def __init__(self):
        self.refresh_calls = []

    async def refresh(self, item):
        self.refresh_calls.append(item)


@pytest.mark.asyncio
async def test_batch_ingestion_calls_all_alerts(monkeypatch):
    session = FakeSession()
    seen = []

    async def fake_ingest_alert(session_obj, payload, *, correlation_id, idempotency_key, request_metadata):
        seen.append((payload.summary, idempotency_key))
        return SimpleNamespace(id=uuid4(), incident_id=uuid4(), summary=payload.summary)

    monkeypatch.setattr('core.storage.ingest_alert', fake_ingest_alert)

    batch = AlertBatchIn(
        alerts=[
            AlertIn(summary='a1', payload={'message': 'one'}),
            AlertIn(summary='a2', payload={'message': 'two'}),
            AlertIn(summary='a3', payload={'message': 'three'}),
        ]
    )
    results = await ingest_alert_batch(session, batch.alerts, correlation_id=None, idempotency_key='idem', request_metadata={})

    assert len(results) == 3
    assert [item[0] for item in seen] == ['a1', 'a2', 'a3']
    assert [item[1] for item in seen] == ['idem:0', 'idem:1', 'idem:2']


@pytest.mark.asyncio
async def test_recent_alerts_summary_filters_by_time(monkeypatch):
    captured = {}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class QuerySession:
        async def execute(self, stmt):
            captured['stmt'] = stmt
            return FakeResult()

    session = QuerySession()
    await recent_alerts_summary(session, hours=6, limit=10)

    compiled = str(captured['stmt'])
    assert 'alerts.created_at >=' in compiled or 'alerts.created_at >' in compiled
    assert 'LIMIT' in compiled.upper()


@pytest.mark.parametrize(
    ('resolved_offset_minutes', 'observed_offset_minutes', 'expected'),
    [(-30, 10, True), (-30, -5, False), (-60 * 30, 5, False)],
)
def test_should_reopen_incident_only_for_fresh_post_resolution_alerts(resolved_offset_minutes, observed_offset_minutes, expected):
    now = utcnow()
    incident = SimpleNamespace(
        status=IncidentStatus.RESOLVED,
        resolved_at=now + timedelta(minutes=resolved_offset_minutes),
    )
    observed_at = now + timedelta(minutes=observed_offset_minutes)
    assert should_reopen_incident(incident, observed_at=observed_at, stale_after_hours=24) is expected


def test_resolved_alert_uses_ends_at_timestamp():
    alert = AlertIn(
        payload={
            'status': 'resolved',
            'startsAt': '2026-05-03T08:00:00Z',
            'endsAt': '2026-05-03T08:30:00Z',
        }
    )

    assert is_resolved_alert(alert)
    assert _payload_received_at(alert).isoformat() == '2026-05-03T08:30:00+00:00'
