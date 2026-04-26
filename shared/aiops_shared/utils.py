from datetime import datetime, timezone

SEVERITY_RANK = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'unknown': 0}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clamp_page_size(page_size: int, default: int = 20, maximum: int = 100) -> int:
    if page_size <= 0:
        return default
    return min(page_size, maximum)


def health_payload(service: str, database: str = 'unknown', readiness: str = 'unknown', *, config_version: str = 'v1') -> dict[str, str]:
    return {
        'status': 'ok',
        'service': service,
        'database': database,
        'readiness': readiness,
        'config_version': config_version,
        'timestamp': utcnow().isoformat(),
    }


def calculate_mttr_seconds(resolved_at: datetime | None, first_seen_at: datetime | None) -> int | None:
    if not resolved_at or not first_seen_at:
        return None
    return int((resolved_at - first_seen_at).total_seconds())


def choose_higher_severity(current: str, incoming: str) -> str:
    current_rank = SEVERITY_RANK.get((current or 'unknown').lower(), 0)
    incoming_rank = SEVERITY_RANK.get((incoming or 'unknown').lower(), 0)
    return incoming if incoming_rank >= current_rank else current
