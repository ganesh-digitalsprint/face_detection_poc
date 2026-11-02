from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import DbEngine, DetectorBackend


class DatabaseConfig(BaseModel):
    """Everything needed to connect to any of the supported database engines.

    Only the fields relevant to the chosen `engine` are used; the others are
    ignored, so the same form/payload shape works for every engine and the
    UI can keep all fields visible and simply grey out the irrelevant ones.
    """

    engine: DbEngine = "sqlite"
    sqlite_path: str = "storage/app.db"
    host: str = "localhost"
    port: int = 5432
    user: str = ""
    password: str = ""
    database: str = "branch_monitoring"
    oracle_service_name: str = ""

    def redacted(self) -> "DatabaseConfig":
        copy = self.model_copy()
        if copy.password:
            copy.password = "********"
        return copy


class DatabaseTestResult(BaseModel):
    ok: bool
    engine: DbEngine
    message: str
    latency_ms: float | None = None


class ThresholdConfig(BaseModel):
    """Tunable business-logic thresholds for the five scenarios.

    Illustrative defaults only - every value is meant to be adjusted per
    camera/zone during a real pilot, as noted throughout the workflow docs.
    """

    loiter_seconds_business_hours: int = Field(300, description="Task 1 - default dwell threshold (s), open hours")
    loiter_seconds_after_hours: int = Field(60, description="Task 1 - default dwell threshold (s), after hours")
    lingering_radius_m: float = Field(3.0, description="Task 1.2 - max radius (m) to count as 'standing still'")

    gathering_min_people: int = Field(3, description="Task 2 - minimum group size")
    gathering_distance_m: float = Field(1.5, description="Task 2 - max distance (m) between members")
    gathering_persistence_seconds: int = Field(10, description="Task 2 - time group must hold before confirming")

    movement_window_seconds: int = Field(30, description="Task 3 - sliding window for path features")
    movement_tortuosity_threshold: float = Field(3.0, description="Task 3 - path-length / displacement ratio")
    movement_running_speed_mps: float = Field(2.5, description="Task 3 - speed above which motion is 'running'")

    after_hours_grace_minutes: int = Field(10, description="Task 4 - grace period around opening/closing")
    after_hours_min_dwell_seconds: int = Field(4, description="Task 4 - min dwell before counting as intrusion")

    weapon_confidence_threshold: float = Field(0.35, description="Task 5.1 - min confidence to raise a weapon flag")
    fight_confidence_threshold: float = Field(0.5, description="Task 5.3 - min confidence to raise a fight flag")
    critical_override_on_weapon: bool = Field(True, description="Task 5.5 - weapon held => force CRITICAL severity")

    dedupe_cooldown_seconds: int = Field(20, description="Minimum gap before the same track/zone can re-alert")

    # Kept so existing runtime_config.json files / the Settings page still load.
    # NOTE: the detector backend is now read from .env (PERSON_DETECTOR_BACKEND),
    # this field is ignored by the camera workers.
    detector_backend: DetectorBackend = "rfdetr"
    processing_fps: int = 5

    # --- Evidence storage (snapshots + clips only for SUSPICIOUS events) ---
    evidence_min_severity: str = Field("high", description="Snapshot+clip only if severity >= this (info|low|medium|high|critical). Weapon/fighting always qualify.")
    evidence_cooldown_seconds: int = Field(60, description="Min gap between evidence sets for the same camera+scenario")
    evidence_max_per_day: int = Field(150, description="Daily cap on evidence sets (critical/weapon/fighting exempt)")
    evidence_post_roll_seconds: int = Field(5, description="Seconds of footage kept AFTER the trigger in the clip")
    evidence_retention_days: int = Field(7, description="Evidence files older than this are deleted automatically")
    storage_max_mb: int = Field(2048, description="Hard cap for snapshots+clips; oldest are deleted beyond it")

    # --- Pose / people ---
    fall_hold_seconds: float = Field(2.0, description="Lying posture must be held this long to count as a fall")
    group_distance_factor: float = Field(0.9, description="People closer than this x body-height are counted as one group")


class NotificationConfig(BaseModel):
    webhook_url: str = ""


class RuntimeConfig(BaseModel):
    thresholds: ThresholdConfig = ThresholdConfig()
    notifications: NotificationConfig = NotificationConfig()
    operating_hours: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "mon": ["10:00", "20:00"], "tue": ["10:00", "20:00"], "wed": ["10:00", "20:00"],
            "thu": ["10:00", "20:00"], "fri": ["10:00", "20:00"], "sat": ["10:00", "18:00"],
            "sun": [],
        },
        description="Branch opening hours per weekday, 24h HH:MM, empty list = closed all day",
    )
