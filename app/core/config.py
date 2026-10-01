"""Centralized application configuration.

All values can be overridden through environment variables or a ``.env`` file
(variable names are case-insensitive). This module intentionally contains no
database connection code and no DeepFace logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DistanceMetric = Literal["cosine", "euclidean", "euclidean_l2"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    # Human-readable service name (shown in Swagger and /health).
    APP_NAME: str = "Face Recognition POC"
    # Service version reported by the API.
    APP_VERSION: str = "1.0.0"
    # Enables debug behaviour (e.g. verbose errors in local development).
    DEBUG: bool = False
    WARMUP_MODEL_ON_STARTUP: bool = False
    CORS_ALLOW_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Root log level used by app.core.logging.setup_logging().
    LOG_LEVEL: LogLevel = "INFO"

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # SQLAlchemy URL for PostgreSQL structured application data.
    # The default is a placeholder only; set the real value in .env.
    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:root@localhost:5432/face_recognition_db"
    )
    QDRANT_URL: str = "https://d0f75223-0ea8-44dd-9fe4-8b1e3d403d96.eu-west-1-0.aws.cloud.qdrant.io"
    QDRANT_API_KEY: SecretStr = SecretStr("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6YjZhMTM3MWItZDcxZS00YjljLTkzMTYtNjc3NjQxYWRkNjcwIn0.fFo_UXwmXVnlTIEJchz6NpGKaffR2EJA8Na23FqRWwY")
    QDRANT_COLLECTION_NAME: str = Field(default="face_embeddings", min_length=1)

    # ------------------------------------------------------------------
    # Face recognition
    # ------------------------------------------------------------------
    # Recognition (embedding) model, accessed through DeepFace.
    # Registration and recognition MUST use the same model.
    FACE_RECOGNITION_MODEL: str = "ArcFace"
    # DeepFace detector backend (e.g. retinaface, opencv, mtcnn, ssd).
    FACE_DETECTOR_BACKEND: str = "retinaface"
    # Distance metric used to compare embeddings. Cosine is the default.
    FACE_DISTANCE_METRIC: DistanceMetric = "cosine"
    # Maximum DISTANCE (not a probability) at which two faces are treated as
    # the same person; a match requires distance <= threshold.
    # 0.68 is DeepFace's published ArcFace/cosine default and is PROVISIONAL.
    # It must be re-evaluated on this project's own dataset and cameras.
    FACE_RECOGNITION_THRESHOLD: float = Field(default=0.68, gt=0.0)

    # ------------------------------------------------------------------
    # Video / webcam
    # ------------------------------------------------------------------
    # Run database recognition once every N frames per track (not every frame).
    RECOGNITION_INTERVAL_FRAMES: int = Field(default=15, ge=1)
    # Maximum number of faces processed per frame/image.
    MAX_FACES: int = Field(default=20, ge=1)
    # OpenCV camera index used for webcam input.
    WEBCAM_INDEX: int = Field(default=0, ge=0)
    RTSP_URLS: list[SecretStr] = Field(default_factory=list)
    RTSP_RECONNECT_ATTEMPTS: int = Field(default=5, ge=0)
    RTSP_RECONNECT_DELAY_SECONDS: float = Field(default=2.0, ge=0.1)
    RTSP_READ_TIMEOUT_MS: int = Field(default=5000, ge=100)
    MAX_VIDEO_UPLOAD_MB: int = Field(default=500, ge=1)
    # Longest allowed frame side in pixels; larger frames are downscaled
    # (aspect ratio preserved) before processing.
    VIDEO_MAX_FRAME_SIZE: int = Field(default=1280, ge=64)

    # ------------------------------------------------------------------
    # Tracking
    # ------------------------------------------------------------------
    # Minimum bounding-box IoU for a detection to continue an existing track.
    TRACK_IOU_THRESHOLD: float = Field(default=0.3, gt=0.0, le=1.0)
    # A track is removed after this many consecutive frames without a match.
    MAX_TRACK_MISSED_FRAMES: int = Field(
        default=15, ge=1,
        validation_alias=AliasChoices("MAX_TRACK_MISSED_FRAMES", "TRACK_MAX_MISSED_FRAMES"),
    )
    TRACK_MAX_MISSED_FRAMES: int = Field(default=15, ge=1, exclude=True)
    # A track that already has an identity only changes it (to another person
    # or to Unknown) after this many CONSECUTIVE contradicting recognitions.
    # 1 = change immediately. Guards against a single blurry frame flipping IDs.
    TRACK_IDENTITY_CHANGE_CONFIRMATIONS: int = Field(default=2, ge=1)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    # Where enrollment (registration) images are saved.
    ENROLLMENT_UPLOAD_DIR: Path = Path("uploads/enrollment")
    # Where test / evaluation images are saved.
    TEST_UPLOAD_DIR: Path = Path("uploads/test")
    VIDEO_UPLOAD_DIR: Path = Path("uploads/video-input")
    VIDEO_OUTPUT_DIR: Path = Path("uploads/video-output")

    @field_validator("FACE_RECOGNITION_MODEL", "FACE_DETECTOR_BACKEND")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    def ensure_directories(self) -> None:
        """Create the upload directories if missing.

        Called explicitly at application startup, never at import time.
        """
        self.ENROLLMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
