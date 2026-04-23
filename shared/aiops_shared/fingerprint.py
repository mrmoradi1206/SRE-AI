import hashlib
import json


FINGERPRINT_KEYS = ['alertname', 'instance', 'job']


def generate_fingerprint(labels: dict) -> str:
    payload = {key: labels.get(key, '') for key in sorted(FINGERPRINT_KEYS)}
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
