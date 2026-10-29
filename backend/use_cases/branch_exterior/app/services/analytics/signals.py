from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.zone import Zone


@dataclass
class ScenarioSignal:
    scenario: str  # loitering | gathering | movement | intrusion | anomaly
    track_ids: list[int]
    message: str
    confidence: float
    zone: Zone | None = None
    severity_hint: str = "medium"  # info | low | medium | high | critical
    meta: dict = field(default_factory=dict)
    dedupe_key: str = ""
