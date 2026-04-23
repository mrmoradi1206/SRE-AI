from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    labels: dict[str, Any]
    annotations: dict[str, Any] | None = None
    status: str = 'firing'
    startsAt: datetime | None = None
    endsAt: datetime | None = None


class AlertWebhookRequest(BaseModel):
    alerts: list[AlertPayload] = Field(default_factory=list)


class AlertResponse(BaseModel):
    incident_id: UUID
    alert_id: UUID
    is_new_incident: bool
    fingerprint: str


class Recommendation(BaseModel):
    priority: int
    action: str
    rationale: str


class AnalysisResponse(BaseModel):
    root_cause: str
    diagnosis: str
    business_impact: str
    is_recurring: bool
    recurrence_note: str
    recommendations: list[Recommendation]
    severity: str
    confidence: float


class AnalyzeRequest(BaseModel):
    incident_id: UUID


class ReportRequest(BaseModel):
    incident_id: UUID
