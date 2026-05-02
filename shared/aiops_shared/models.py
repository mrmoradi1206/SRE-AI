import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_class]


class IncidentStatus(str, enum.Enum):
    OPEN = 'open'
    INVESTIGATING = 'investigating'
    MITIGATING = 'mitigating'
    RESOLVED = 'resolved'
    CLOSED = 'closed'


class IncidentSeverity(str, enum.Enum):
    CRITICAL = 'critical'
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    UNKNOWN = 'unknown'


class DeadLetterStatus(str, enum.Enum):
    PENDING = 'pending'
    RETRYING = 'retrying'
    PROCESSED = 'processed'
    FAILED = 'failed'


class QueueStatus(str, enum.Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    RETRYING = 'retrying'
    COMPLETED = 'completed'
    FAILED = 'failed'


class Incident(Base):
    __tablename__ = 'incidents'
    __table_args__ = (
        Index('ix_incidents_status_last_seen', 'status', 'last_seen_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    grouping_key: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    dedup_key: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name='incident_severity', values_callable=_enum_values),
        nullable=False,
        default=IncidentSeverity.UNKNOWN,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name='incident_status', values_callable=_enum_values),
        nullable=False,
        default=IncidentStatus.OPEN,
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(Text)
    escalated_to: Mapped[str | None] = mapped_column(Text)
    mitigated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mitigated_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[str | None] = mapped_column(Text)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_violated: Mapped[bool] = mapped_column(nullable=False, default=False)
    mttr_seconds: Mapped[int | None] = mapped_column(Integer)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    alerts: Mapped[list['Alert']] = relationship(back_populates='incident', cascade='all, delete-orphan')
    events: Mapped[list['IncidentEvent']] = relationship(back_populates='incident', cascade='all, delete-orphan')


class Alert(Base):
    __tablename__ = 'alerts'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    grouping_key: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    dedup_key: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    event_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default='unknown')
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    incident: Mapped['Incident'] = relationship(back_populates='alerts')
    history: Mapped[list['AlertEvent']] = relationship(back_populates='alert', cascade='all, delete-orphan')


class AlertEvent(Base):
    __tablename__ = 'alert_events'
    __table_args__ = (
        UniqueConstraint('alert_id', 'version', name='uq_alert_events_version'),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('alerts.id', ondelete='CASCADE'), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, default='ingested')
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    alert: Mapped['Alert'] = relationship(back_populates='history')


class IncidentEvent(Base):
    __tablename__ = 'incident_events'
    __table_args__ = (
        UniqueConstraint('stream_id', 'sequence_number', name='uq_incident_events_sequence'),
        Index('ix_incident_events_stream_sequence', 'stream_id', 'sequence_number'),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stream_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False, index=True)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)

    incident: Mapped['Incident'] = relationship(back_populates='events')


class AISettings(Base):
    __tablename__ = 'ai_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text)
    extra_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DeadLetterQueue(Base):
    __tablename__ = 'dead_letter_queue'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DeadLetterStatus] = mapped_column(
        Enum(DeadLetterStatus, name='dead_letter_status', values_callable=_enum_values),
        nullable=False,
        default=DeadLetterStatus.PENDING,
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class EventQueue(Base):
    __tablename__ = 'event_queue'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    stream_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[QueueStatus] = mapped_column(
        Enum(QueueStatus, name='queue_status', values_callable=_enum_values),
        nullable=False,
        default=QueueStatus.PENDING,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
