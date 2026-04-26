import hashlib
import json
from typing import Any


STABLE_FIELDS = ('alertname', 'service', 'instance', 'job', 'cluster', 'namespace', 'severity', 'source')


def _extract_labels(alert_payload: dict[str, Any]) -> dict[str, Any]:
    labels = alert_payload.get('labels')
    return labels if isinstance(labels, dict) else {}


def compute_grouping_key(alert_payload: dict[str, Any]) -> str:
    labels = _extract_labels(alert_payload)
    grouping = {
        'alertname': labels.get('alertname') or alert_payload.get('alertname'),
        'service': labels.get('service') or alert_payload.get('service'),
        'cluster': labels.get('cluster') or alert_payload.get('cluster'),
        'namespace': labels.get('namespace') or alert_payload.get('namespace'),
    }
    compact = {key: value for key, value in grouping.items() if value not in (None, '', [], {})}
    encoded = json.dumps(compact or alert_payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def compute_dedup_key(alert_payload: dict[str, Any]) -> str:
    labels = _extract_labels(alert_payload)
    dedup = {
        'alertname': labels.get('alertname') or alert_payload.get('alertname'),
        'instance': labels.get('instance') or alert_payload.get('instance'),
        'job': labels.get('job') or alert_payload.get('job'),
        'source': alert_payload.get('source') or labels.get('source'),
    }
    compact = {key: value for key, value in dedup.items() if value not in (None, '', [], {})}
    encoded = json.dumps(compact or alert_payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def compute_fingerprint(alert_payload: dict[str, Any]) -> str:
    labels = _extract_labels(alert_payload)
    flattened = {
        'alertname': labels.get('alertname') or alert_payload.get('alertname'),
        'service': labels.get('service') or alert_payload.get('service'),
        'instance': labels.get('instance') or alert_payload.get('instance'),
        'job': labels.get('job') or alert_payload.get('job'),
        'cluster': labels.get('cluster') or alert_payload.get('cluster'),
        'namespace': labels.get('namespace') or alert_payload.get('namespace'),
        'severity': labels.get('severity') or alert_payload.get('severity'),
        'source': alert_payload.get('source') or labels.get('source'),
    }
    filtered = {key: value for key, value in flattened.items() if value not in (None, '', [], {})}
    encoded = json.dumps(filtered or alert_payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def normalize_severity(alert_payload: dict[str, Any], fallback: str = 'unknown') -> str:
    labels = _extract_labels(alert_payload)
    severity = labels.get('severity') or alert_payload.get('severity') or fallback
    normalized = str(severity).strip().lower()
    aliases = {
        'sev0': 'critical',
        'sev1': 'high',
        'sev2': 'medium',
        'sev3': 'low',
        'warning': 'medium',
    }
    return aliases.get(normalized, normalized or fallback)
