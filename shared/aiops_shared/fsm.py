from dataclasses import dataclass
from datetime import datetime

from .models import Incident, IncidentStatus


@dataclass(frozen=True)
class TransitionResult:
    from_status: str
    to_status: str
    changed: bool
    applied_at: datetime
    actor: str
    reason: str


ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING},
    IncidentStatus.INVESTIGATING: {IncidentStatus.MITIGATING},
    IncidentStatus.MITIGATING: {IncidentStatus.RESOLVED},
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED},
    IncidentStatus.CLOSED: set(),
}


class InvalidIncidentTransitionError(ValueError):
    pass


def can_transition(current: IncidentStatus, target: IncidentStatus) -> bool:
    return current == target or target in ALLOWED_TRANSITIONS.get(current, set())


def apply_transition(incident: Incident, target: IncidentStatus, actor: str, reason: str, at: datetime) -> TransitionResult:
    current = incident.status
    if not can_transition(current, target):
        raise InvalidIncidentTransitionError(f'invalid transition from {current.value} to {target.value}')
    if current == target:
        return TransitionResult(current.value, target.value, False, at, actor, reason)

    incident.status = target
    if target == IncidentStatus.INVESTIGATING:
        incident.acknowledged_at = at
        incident.acknowledged_by = actor
    elif target == IncidentStatus.MITIGATING:
        incident.mitigated_at = at
        incident.mitigated_by = actor
    elif target == IncidentStatus.RESOLVED:
        incident.resolved_at = at
        incident.resolved_by = actor
    elif target == IncidentStatus.CLOSED:
        incident.closed_at = at
        incident.closed_by = actor

    return TransitionResult(current.value, target.value, True, at, actor, reason)
