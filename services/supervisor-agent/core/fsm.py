from aiops_shared.fsm import TransitionResult, apply_transition, can_transition
from aiops_shared.models import IncidentStatus

TRANSITION_MAP = {
    IncidentStatus.OPEN: [IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED, IncidentStatus.CLOSED],
    IncidentStatus.INVESTIGATING: [IncidentStatus.MITIGATING, IncidentStatus.RESOLVED, IncidentStatus.CLOSED],
    IncidentStatus.MITIGATING: [IncidentStatus.RESOLVED, IncidentStatus.CLOSED],
    IncidentStatus.RESOLVED: [IncidentStatus.CLOSED],
    IncidentStatus.CLOSED: [],
}

__all__ = ['IncidentStatus', 'TRANSITION_MAP', 'TransitionResult', 'apply_transition', 'can_transition']
