from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Scenario = Literal["loitering", "gathering", "movement", "intrusion", "anomaly", "simulated"]
Severity = Literal["info", "low", "medium", "high", "critical"]
EventStatus = Literal["open", "under_review", "confirmed", "false_positive", "closed"]

SEVERITY_ORDER: dict[Severity, int] = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

SCENARIO_LABELS: dict[Scenario, str] = {
    "loitering": "Task 1 - Loitering",
    "gathering": "Task 2 - Suspicious gathering",
    "movement": "Task 3 - Unusual movement",
    "intrusion": "Task 4 - After-hours intrusion",
    "anomaly": "Task 5 - AI-based anomaly",
    "simulated": "Simulated demo alert",
}


class EventCreate(BaseModel):
    camera_id: str
    camera_name: str = ""
    zone_id: str | None = None
    zone_name: str = ""
    scenario: Scenario
    severity: Severity
    track_ids: list[int] = []
    message: str = ""
    confidence: float = 0.0
    snapshot_path: str = ""
    clip_path: str = ""
    meta: dict = {}
    dedupe_key: str = ""


class EventReview(BaseModel):
    status: Literal["confirmed", "false_positive", "under_review", "closed"]
    reviewer_remarks: str = ""


class Event(BaseModel):
    id: str
    camera_id: str
    camera_name: str = ""
    zone_id: str | None = None
    zone_name: str = ""
    scenario: Scenario
    severity: Severity
    status: EventStatus
    track_ids: list[int] = []
    message: str = ""
    confidence: float = 0.0
    snapshot_path: str = ""
    clip_path: str = ""
    meta: dict = {}
    reviewer_remarks: str = ""
    dedupe_key: str = ""
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class EventFilter(BaseModel):
    camera_id: str | None = None
    scenario: Scenario | None = None
    severity: Severity | None = None
    status: EventStatus | None = None
    since: datetime | None = None
    limit: int = 200
