"""Application settings.

Values come from environment variables / a `.env` file (see `.env.example`).
Database credentials specifically can *also* be changed at runtime from the
Settings page in the UI; when that happens they are persisted to
`backend/config/db_config.json` and take priority over `.env` on the next
lookup (see `app.services.db_config_service`).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DbEngine = Literal["sqlite", "postgres", "mysql", "oracle", "mongodb"]
DetectorBackend = Literal["motion", "hog", "rfdetr"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # General ----------------------------------------------------------------
    app_name: str = "Branch Exterior Monitoring & Anomaly Detection"
    environment: str = "development"
    api_prefix: str = "/api"
    cors_origins: str = "*"
    api_key: str = ""

    # Database (defaults; may be overridden at runtime, see db_config_service)
    db_engine: DbEngine = "sqlite"
    db_sqlite_path: str = "storage/app.db"
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = ""
    db_password: str = ""
    db_name: str = "branch_monitoring"
    db_oracle_service_name: str = ""

    # Storage ------------------------------------------------------------------
    storage_dir: str = "storage"
    snapshot_dir: str = "storage/snapshots"
    clip_dir: str = "storage/clips"
    upload_dir: str = "storage/uploads"
    sample_video_dir: str = "storage/sample_videos"
    guard_face_dir: str = "storage/guard_faces"

    # Only one camera/video is analysed at a time (the one picked in the Live
    # Monitoring dropdown). Every other camera is idle and uses no CPU.
    # Set to false to run every enabled camera at once (e.g. a real multi-camera site).
    single_active_camera: bool = True

    # Detection pipeline ---------------------------------------------------
    # rfdetr (default) | motion | hog. The detector is chosen ONLY from here
    # (.env), not from the Settings page, and needs a restart to change.
    person_detector_backend: DetectorBackend = "rfdetr"
    rfdetr_model_size: Literal["auto", "nano", "small", "medium", "large", "base"] = "auto"  # auto: medium on GPU, nano on CPU
    rfdetr_device: Literal["auto", "cpu", "cuda"] = "auto"
    rfdetr_threshold: float = 0.40       # confidence needed to START a person/vehicle track
    rfdetr_low_threshold: float = 0.20   # lower-confidence boxes still extend existing tracks (ByteTrack)
    # Tiled detection for tiny/far people (wide street shots): the frame is also cut into
    # overlapping tiles so small people reach the model ~2x bigger. Costs cols*rows extra
    # passes, so it only runs every `detect_tile_every` passes and on frames >= 900 px wide.
    detect_tiles: str = "2x2"            # "off" | "2x1" | "2x2" | "3x2" ...
    detect_tile_every: int = 3
    detect_every_n_frames: int = 1       # run RF-DETR on every Nth processed frame. Keep at 1: sparse detection breaks tracking of running/jumping people

    # Zone alerts: what counts as "suspicious at a zone" (zones set to alert mode suspicious / enter / near)
    zone_group_min_people: int = 3
    zone_group_seconds: float = 15.0        # 3+ people at the zone for this long = a gathering worth an alert
    zone_stare_glances: int = 3             # glances toward the zone within 12 s ...
    zone_stare_seconds: float = 4.0         # ... or one continuous look this long
    zone_rush_bh_per_s: float = 1.1         # running speed (body heights/second) toward the zone
    zone_tamper_agitation: float = 2.5      # vigorous arm movement while hands are on the zone

    # Bags (COCO backpack / handbag / suitcase) - used by the "unattended bag" rule
    bag_detection_enabled: bool = True
    bag_threshold: float = 0.35
    unattended_bag_seconds: float = 20.0

    weapon_detector_enabled: bool = True
    weapon_coco_classes_enabled: bool = True   # COCO "knife"/"baseball bat" from the same RF-DETR pass
    weapon_coco_threshold: float = 0.45
    weapon_model_path: str = ""                # optional fine-tuned RF-DETR checkpoint (.pth) for gun/knife/...
    weapon_class_names: str = "gun,knife"      # only used if the checkpoint doesn't carry its own class names
    weapon_custom_threshold: float = 0.45
    weapon_every_n_frames: int = 2             # custom weapon model (full frame) runs every Nth detection pass
    weapon_model_size: Literal["nano", "small", "medium", "large", "base"] = "nano"  # size the custom checkpoint was trained with
    # Zoom-in weapon pass: crops around each person are re-checked at higher effective
    # resolution, which is what makes hand-held knives/bats visible at CCTV distances.
    weapon_crop_pass_enabled: bool = True
    weapon_crop_threshold: float = 0.35
    weapon_crop_every_n_passes: int = 2
    weapon_crop_max_people: int = 3
    weapon_confirm_hits: int = 3               # weapon must be seen in this many checks on the same person

    pose_enabled: bool = True
    pose_every_n_frames: int = 1
    pose_max_people: int = 6
    pose_model: str = (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-s_simcc-body7_pt-body7_420e-256x192-acd4a1ef_20230504.zip"
    )  # rtmpose-s: light enough for a CPU laptop. A local .onnx path also works.

    # Action sensitivity (starting values - tune on your own footage)
    fight_agitation_threshold: float = 3.0   # lower = more sensitive (arm speed in torso-lengths/second)
    fight_strike_speed: float = 3.5
    run_bodyheights_per_s: float = 1.1       # speed (body heights per second) above which a person counts as running

    face_recognition_enabled: bool = True
    processing_fps: int = 10   # upper limit; real speed is whatever the CPU manages
    cpu_threads: int = 0       # torch threads. 0 = auto (CPU cores - 2) so the web server always has room to answer
    frame_width: int = 1280   # analysis width (no upscaling). Small far-away people need pixels.

    # Notifications ----------------------------------------------------------
    notify_webhook_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
