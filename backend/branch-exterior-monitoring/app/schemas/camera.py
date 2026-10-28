from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CameraType = Literal["rtsp", "webcam", "upload", "folder", "simulated"]

# "simulated" is its own explicit camera type (not a checkbox bolted onto the
# other four) precisely so that choosing a real file can never be silently
# overridden by a leftover "demo mode" flag - see app/api/routes/cameras.py,
# which derives `simulation_mode` from `cam_type` rather than trusting a
# separately-submitted value, and app/services/stream_worker.py, which keys
# its behaviour off `cam_type == "simulated"` rather than the flag alone.


class CameraCreate(BaseModel):
    name: str
    cam_type: CameraType
    source: str = Field(
        "", description="RTSP/HTTP URL, webcam device index, or a file path under storage/ - not required when cam_type is 'simulated'"
    )
    username: str = ""
    password: str = ""
    location: str = ""
    enabled: bool = True
    simulation_mode: bool = Field(
        False,
        description=(
            "Deprecated as a user-facing input - the API forces this to match "
            "cam_type == 'simulated' regardless of what is submitted here. "
            "Retained only so existing stored records still validate."
        ),
    )
    loop_video: bool = True


class CameraUpdate(BaseModel):
    name: str | None = None
    source: str | None = None
    username: str | None = None
    password: str | None = None
    location: str | None = None
    enabled: bool | None = None
    loop_video: bool | None = None
    # cam_type and simulation_mode are intentionally not editable after
    # creation - whether a camera is simulated is fixed at creation time by
    # its cam_type, so there is nothing consistent to PATCH here.


class Camera(BaseModel):
    id: str
    name: str
    cam_type: CameraType
    source: str
    username: str = ""
    password: str = ""
    location: str = ""
    enabled: bool = True
    simulation_mode: bool = False
    loop_video: bool = True
    created_at: datetime

    def redacted(self) -> "Camera":
        c = self.model_copy()
        if c.password:
            c.password = "********"
        return c


class CameraStatus(BaseModel):
    camera_id: str
    running: bool
    fps: float = 0.0
    frame_count: int = 0
    active_tracks: int = 0
    vehicle_count: int = 0
    last_error: str | None = None
    open_events: int = 0
    # People counting (confirmed, currently-visible people only)
    people_now: int = 0
    individuals: int = 0          # people not near anyone else
    groups: list[int] = []        # sizes of groups, e.g. [3, 2]
    largest_group: int = 0
    unique_people: int = 0        # distinct people seen since the video started/looped
    peak_people: int = 0
    detector: str = ""            # which detector is actually running (shows RF-DETR vs fallback)
    pose_active: bool = False
    # Threat KPIs
    weapons_now: int = 0          # weapon-like objects visible right now
    armed_people: int = 0         # people confirmed holding one
    weapons_seen: int = 0         # distinct armed people since the video started/looped
    weapon_labels: list[str] = []
    weapon_engine: str = ""       # what is actually looking for weapons (e.g. "COCO knife/bat + NO gun model loaded")
    fighting_now: int = 0
    fallen_now: int = 0
    running_now: int = 0
    jumping_now: int = 0
    threat_level: str = "NORMAL"     # NORMAL | ELEVATED | HIGH | CRITICAL
    threat_reasons: list[str] = []
    prep_info: str = ""              # e.g. "black bars removed"
    tiles_active: bool = False
    debug_overlay: bool = False
    heatmap_overlay: bool = False
    features: list[str] = []         # plain-language list of what the analysis is doing right now
    behavior_counts: dict[str, int] = {}   # incidents per rule since this video started
    zone_alerts: list[str] = []      # zones with a person at them right now, e.g. "ATM front (inside, 2)"