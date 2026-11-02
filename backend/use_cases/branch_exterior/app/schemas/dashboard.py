from __future__ import annotations

from pydantic import BaseModel


class SeverityCount(BaseModel):
    severity: str
    count: int


class ScenarioCount(BaseModel):
    scenario: str
    count: int


class HourlyCount(BaseModel):
    hour: str
    count: int


class DashboardSummary(BaseModel):
    total_events: int
    open_events: int
    critical_open: int
    events_today: int
    cameras_online: int
    cameras_total: int
    guards_enrolled: int
    by_severity: list[SeverityCount]
    by_scenario: list[ScenarioCount]
    by_hour: list[HourlyCount]
    db_engine: str
