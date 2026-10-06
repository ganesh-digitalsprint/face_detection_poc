"""Centralized application configuration.

Application and infrastructure values come from environment variables or
``.env``; ML/runtime tuning is loaded from ``config/models.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
ComputeDevice = Literal["auto", "cpu", "gpu"]


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
    # SQLAlchemy URL for PostgreSQL structured application data; supply it in .env.
    DATABASE_URL: str = ""
    QDRANT_URL: str = ""
    QDRANT_API_KEY: SecretStr = SecretStr("")
    QDRANT_COLLECTION_NAME: str = Field(default="face_embeddings", min_length=1)

    # ------------------------------------------------------------------
    # Optional selectors overriding config/models.yaml.
    RECOGNITION_MODEL: str | None = None
    PERFORMANCE_PROFILE: str | None = None
    COMPUTE_DEVICE: ComputeDevice | None = None

    # ------------------------------------------------------------------
    # Video / webcam
    # ------------------------------------------------------------------
    # OpenCV camera index used for webcam input.
    WEBCAM_INDEX: int = Field(default=0, ge=0)
    RTSP_URLS: list[SecretStr] = Field(default_factory=list)
    RTSP_RECONNECT_ATTEMPTS: int = Field(default=5, ge=0)
    RTSP_RECONNECT_DELAY_SECONDS: float = Field(default=2.0, ge=0.1)
    RTSP_READ_TIMEOUT_MS: int = Field(default=5000, ge=100)
    MAX_VIDEO_UPLOAD_MB: int = Field(default=500, ge=1)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    # Where enrollment (registration) images are saved.
    ENROLLMENT_UPLOAD_DIR: Path = Path("uploads/enrollment")
    # Where test / evaluation images are saved.
    TEST_UPLOAD_DIR: Path = Path("uploads/test")
    VIDEO_UPLOAD_DIR: Path = Path("uploads/video-input")
    VIDEO_OUTPUT_DIR: Path = Path("uploads/video-output")
    def ensure_directories(self) -> None:
        """Create the upload directories if missing.

        Called explicitly at application startup, never at import time.
        """
        self.ENROLLMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
