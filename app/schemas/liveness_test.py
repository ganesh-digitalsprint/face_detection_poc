"""Liveness Test Lab responses. Diagnostic only: no identity, embedding or vault data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: int
    y: int


class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class PoseInfo(BaseModel):
    yaw: float
    pitch: float
    yaw_delta: float | None = None
    pitch_delta: float | None = None
    yaw_degrees: float | None = None
    pitch_degrees: float | None = None
    # FRONTAL | TURNED_LEFT | TURNED_RIGHT | LOOKING_UP | LOOKING_DOWN (subject's own direction)
    direction: str
    is_frontal: bool


class ClarityInfo(BaseModel):
    sharpness: float
    min_sharpness: float
    brightness: float
    face_width: int
    face_height: int
    min_face_px: int
    face_area_ratio: float
    quality: str  # GOOD | FAIR | POOR


class ChallengeInfo(BaseModel):
    challenge: str | None
    passed: bool
    # Signed delta on the challenge axis vs baseline (smile: width delta; blink: openness ratio).
    movement: float
    # Signed pass threshold: movement must reach it in the same direction.
    threshold: float
    hits: int
    required_hits: int
    reason: str


class DetectorResult(BaseModel):
    detector: str
    visible: bool
    not_visible_reason: str | None = None
    bbox: BBox | None = None
    landmarks: dict[str, Point] = Field(default_factory=dict)
    pose: PoseInfo | None = None
    clarity: ClarityInfo | None = None
    elapsed_ms: float
    error: str | None = None


class ThresholdsInfo(BaseModel):
    yaw_pass: float
    pitch_pass: float
    cross_limit: float
    frontal_yaw_max: float
    frontal_pitch_max: float
    required_hits: int
    hold_duration_ms: int
    min_sharpness: float
    min_face_px: int
    available_challenges: list[str]


class LivenessTestAnalysis(BaseModel):
    session_id_prefix: str
    frame_number: int
    image_width: int
    image_height: int
    baseline_ready: bool
    results: list[DetectorResult]
    challenge: ChallengeInfo | None = None
    thresholds: ThresholdsInfo
    angles_are_estimates: bool = True


class TestSessionStarted(BaseModel):
    session_id: str
    thresholds: ThresholdsInfo


class TestChallengeRequest(BaseModel):
    challenge: str | None = None


class TestConfigResponse(BaseModel):
    thresholds: ThresholdsInfo
    detectors: dict[str, bool]


class TestAck(BaseModel):
    ok: bool = True
    session_id_prefix: str
