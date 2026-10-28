from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ZoneType = Literal["entrance", "atm", "side_lane", "forecourt", "rear", "restricted", "other"]

# What should raise an alert at this zone?
#   off        - nothing special (the zone is only used by the loitering / gathering / movement rules)
#   suspicious - RECOMMENDED. A person merely being there is normal and raises nothing. An alert starts only when
#                something suspicious happens IN or AT the zone: a weapon, a fight, 3+ people gathering for a long
#                time, repeated staring toward it, running toward it, jumping, climbing, hands working on it,
#                or any behaviour rule firing for someone there.
#   enter      - RESTRICTED area: alert the moment a person ENTERS or TOUCHES it (plus everything in "suspicious")
#   near       - RESTRICTED area: alert when a person enters, touches or comes close (plus everything in "suspicious")
AlertMode = Literal["off", "suspicious", "enter", "near"]
AlertSeverity = Literal["low", "medium", "high", "critical"]


class Point(BaseModel):
    x: float  # 0..1, fraction of frame width
    y: float  # 0..1, fraction of frame height


class ZoneCreate(BaseModel):
    camera_id: str
    name: str
    zone_type: ZoneType
    restricted: bool = False
    alert_mode: AlertMode = "off"
    alert_severity: AlertSeverity = "high"
    polygon: list[Point]


class ZoneUpdate(BaseModel):
    name: str | None = None
    zone_type: ZoneType | None = None
    restricted: bool | None = None
    alert_mode: AlertMode | None = None
    alert_severity: AlertSeverity | None = None
    polygon: list[Point] | None = None


class Zone(BaseModel):
    id: str
    camera_id: str
    name: str
    zone_type: ZoneType
    restricted: bool
    alert_mode: AlertMode = "off"
    alert_severity: AlertSeverity = "high"
    polygon: list[Point]
    created_at: datetime
