import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import DeadLetterStatus, IncidentSeverity, IncidentStatus, QueueStatus

LEGACY_STATUS_MAP = {'acknowledged': IncidentStatus.INVESTIGATING.value}


class AlertIn(BaseModel):
    event_key: str | None = None
    source: str | None = None
    severity: str | None = None
    grouping_key: str | None = None
    dedup_key: str | None = None
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra='allow')

    @field_validator('event_key', 'source', 'severity', 'grouping_key', 'dedup_key', 'summary')
    @classmethod
    def validate_short_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if len(cleaned) > 512 or any(ch in cleaned for ch in ['\x00', '\r']):
            raise ValueError('field contains invalid text')
        return cleaned

    @field_validator('payload', 'metadata')
    @classmethod
    def validate_json_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        max_bytes = int(os.getenv('MAX_ALERT_JSON_BYTES', '262144'))
        encoded = json.dumps(value, default=str, separators=(',', ':')).encode('utf-8')
        if len(encoded) > max_bytes:
            raise ValueError(f'JSON object exceeds {max_bytes} bytes')
        return value

    @model_validator(mode='before')
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if isinstance(value.get('payload'), dict):
                return value
            payload = {
                key: item
                for key, item in value.items()
                if key not in {'event_key', 'source', 'severity', 'grouping_key', 'dedup_key', 'summary', 'correlation_id', 'metadata'}
            }
            return {
                'event_key': value.get('event_key'),
                'source': value.get('source'),
                'severity': value.get('severity'),
                'grouping_key': value.get('grouping_key'),
                'dedup_key': value.get('dedup_key'),
                'summary': value.get('summary'),
                'correlation_id': value.get('correlation_id'),
                'metadata': value.get('metadata', {}),
                'payload': payload,
            }
        return value


class AlertBatchIn(BaseModel):
    alerts: list[AlertIn] = Field(default_factory=list, min_length=1)

    model_config = ConfigDict(extra='allow')

    @field_validator('alerts')
    @classmethod
    def validate_batch_size(cls, value: list[AlertIn]) -> list[AlertIn]:
        max_alerts = int(os.getenv('MAX_ALERT_BATCH_SIZE', '100'))
        if len(value) > max_alerts:
            raise ValueError(f'batch exceeds {max_alerts} alerts')
        return value


class EventEnvelopeOut(BaseModel):
    event_id: UUID
    stream_id: UUID
    event_version: int
    event_type: str
    actor: str
    causation_id: UUID | None = None
    correlation_id: UUID | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any]
    payload: dict[str, Any]
    created_at: datetime
    sequence_number: int

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode='before')
    @classmethod
    def normalize_event_metadata(cls, value: Any) -> Any:
        if hasattr(value, 'event_metadata') and not hasattr(value, 'metadata'):
            return {
                'event_id': value.event_id,
                'stream_id': value.stream_id,
                'event_version': value.event_version,
                'event_type': value.event_type,
                'actor': value.actor,
                'causation_id': value.causation_id,
                'correlation_id': value.correlation_id,
                'idempotency_key': value.idempotency_key,
                'metadata': value.event_metadata,
                'payload': value.payload,
                'created_at': value.created_at,
                'sequence_number': value.sequence_number,
            }
        return value


class AlertOut(BaseModel):
    id: UUID
    incident_id: UUID
    fingerprint: str
    grouping_key: str
    dedup_key: str
    event_key: str
    source: str | None = None
    severity: str
    correlation_id: UUID | None = None
    payload: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentListItem(BaseModel):
    id: UUID
    fingerprint: str
    grouping_key: str
    dedup_key: str
    summary: str | None = None
    severity: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None = None
    sla_deadline: datetime | None = None
    sla_violated: bool = False
    created_at: datetime
    updated_at: datetime
    alert_count: int = 0
    latest_event_type: str | None = None
    mttr_seconds: int | None = None
    projection_version: int


class IncidentOut(BaseModel):
    id: UUID
    fingerprint: str
    grouping_key: str
    dedup_key: str
    summary: str | None = None
    severity: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_by: str | None = None
    escalated_to: str | None = None
    mitigated_at: datetime | None = None
    mitigated_by: str | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    sla_deadline: datetime | None = None
    sla_violated: bool
    mttr_seconds: int | None = None
    projection_version: int
    created_at: datetime
    updated_at: datetime
    alerts: list[AlertOut] = Field(default_factory=list)
    timeline: list[EventEnvelopeOut] = Field(default_factory=list)


class DashboardStats(BaseModel):
    open_incidents_count: int
    investigating_incidents_count: int
    mitigating_incidents_count: int
    alerts_last_24h: int
    resolved_last_24h: int
    dlq_pending_count: int
    queue_pending_count: int


class AISettingsIn(BaseModel):
    provider: str
    model: str
    api_key: str | None = None
    extra_config: dict[str, Any] = Field(default_factory=dict)


class AISettingsOut(BaseModel):
    id: int | None = None
    provider: str
    model: str
    api_key: str | None = None
    extra_config: dict[str, Any] = Field(default_factory=dict)
    version: int | None = None


class SupervisorAnalyzeIn(BaseModel):
    incident_id: UUID
    reasoning_mode: str = 'balanced'


class SupervisorDecisionOut(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)
    next_state: str
    reasoning_trace: str


class ReportGenerateIn(BaseModel):
    analysis: dict[str, Any] | None = None


class TestWorkflowIn(BaseModel):
    alert: AlertIn | dict[str, Any] | None = None

    model_config = ConfigDict(extra='allow')

    @model_validator(mode='after')
    def ensure_alert_payload(self) -> 'TestWorkflowIn':
        if self.alert is None:
            raw = self.model_dump(exclude={'alert'}, exclude_none=True)
            self.alert = AlertIn.model_validate(raw)
        elif isinstance(self.alert, dict):
            self.alert = AlertIn.model_validate(self.alert)
        return self


class RuntimeSecretsIn(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)


class SupervisorStatusChangeIn(BaseModel):
    incident_id: UUID
    reason: str | None = None
    actor: str = 'supervisor'

    @field_validator('actor')
    @classmethod
    def validate_actor(cls, value: str) -> str:
        return value or 'supervisor'


class IncidentReplayOut(BaseModel):
    incident_id: UUID
    total_events: int
    replayed_state: dict[str, Any]
    events: list[EventEnvelopeOut]


class DeadLetterOut(BaseModel):
    id: int
    queue_key: str
    service: str
    operation: str
    status: DeadLetterStatus
    correlation_id: UUID | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any]
    error_message: str
    retry_count: int
    next_retry_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueueItemOut(BaseModel):
    id: UUID
    topic: str
    stream_id: UUID | None = None
    correlation_id: UUID | None = None
    idempotency_key: str | None = None
    status: QueueStatus
    payload: dict[str, Any]
    not_before: datetime
    retry_count: int
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentFilterIn(BaseModel):
    status: str | None = None
    severity: str | None = None
    fingerprint: str | None = None
    grouping_key: str | None = None
    dedup_key: str | None = None


class CorrelationGraphNode(BaseModel):
    id: str
    label: str
    kind: str


class CorrelationGraphEdge(BaseModel):
    source: str
    target: str
    label: str


class CorrelationGraphOut(BaseModel):
    nodes: list[CorrelationGraphNode]
    edges: list[CorrelationGraphEdge]


def normalize_status_value(status: str | IncidentStatus) -> str:
    if isinstance(status, IncidentStatus):
        return status.value
    return LEGACY_STATUS_MAP.get(status, status)
