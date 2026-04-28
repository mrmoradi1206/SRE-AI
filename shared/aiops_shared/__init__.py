__all__ = [
    'AISettings',
    'Alert',
    'AlertEvent',
    'Base',
    'DeadLetterQueue',
    'EventQueue',
    'Incident',
    'IncidentEvent',
    'IncidentSeverity',
    'IncidentStatus',
    'get_db',
    'get_engine',
    'get_session_factory',
]


def __getattr__(name: str):
    if name in {'Base', 'get_db', 'get_engine', 'get_session_factory'}:
        from . import database

        return getattr(database, name)
    if name in {
        'AISettings',
        'Alert',
        'AlertEvent',
        'DeadLetterQueue',
        'EventQueue',
        'Incident',
        'IncidentEvent',
        'IncidentSeverity',
        'IncidentStatus',
    }:
        from . import models

        return getattr(models, name)
    raise AttributeError(f'module aiops_shared has no attribute {name}')
