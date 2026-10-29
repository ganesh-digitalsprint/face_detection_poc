"""Centralized application configuration.

Application and infrastructure values come from environment variables or
``.env``; ML/runtime tuning is loaded from ``config/models.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
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
    VAULT_REQUIRED_PERSONS: int | None = Field(default=None, ge=1, le=2)
    VAULT_ALLOW_MODE_SELECT: bool | None = None
    VAULT_ROOM_API_KEY: str | None = None

    # Optional server-to-server publication. These credentials never reach the browser.
    ALERT_SERVICE_BASE_URL: str | None = None
    ALERT_SERVICE_TOKEN: SecretStr = SecretStr("")
    ALERT_SERVICE_TIMEOUT_SECONDS: float = Field(default=3.0, ge=0.1, le=10.0)
    ALERT_SERVICE_POLL_SECONDS: float = Field(default=2.0, ge=0.2, le=60.0)

    @field_validator("ALERT_SERVICE_BASE_URL")
    @classmethod
    def validate_alert_service_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("ALERT_SERVICE_BASE_URL must be an http(s) origin without credentials or path")
        return value.strip().rstrip("/")

    # Cloudinary credentials stay on the server and are never serialized.
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: SecretStr = SecretStr("")
    CLOUDINARY_API_SECRET: SecretStr = SecretStr("")
    CLOUDINARY_EVIDENCE_FOLDER: str = "vault-monitoring"
    EVIDENCE_MAX_UPLOAD_BYTES: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    EVIDENCE_UPLOAD_TIMEOUT_SECONDS: int = Field(default=20, ge=1, le=120)
    EVIDENCE_UPLOAD_RETRIES: int = Field(default=2, ge=0, le=5)
    EVIDENCE_URL_TTL_SECONDS: int = Field(default=300, ge=30, le=900)
    EVIDENCE_SPOOL_DIR: str = "var/evidence-spool"

    # ------------------------------------------------------------------
    # Video / webcam
    # ------------------------------------------------------------------
    # OpenCV camera index used for webcam input.
    WEBCAM_INDEX: int = Field(default=0, ge=0)
    RTSP_URLS: list[SecretStr] = Field(default_factory=list)
    # User-entered RTSP destinations may be restricted to these hostnames/domains.
    # When unset, dynamic Vault Room RTSP connections are limited to private IP ranges.
    RTSP_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    RTSP_RECONNECT_ATTEMPTS: int = Field(default=5, ge=0)
    RTSP_RECONNECT_DELAY_SECONDS: float = Field(default=2.0, ge=0.1)
    RTSP_READ_TIMEOUT_MS: int = Field(default=5000, ge=100)
    MAX_VIDEO_UPLOAD_MB: int = Field(default=500, ge=1)

    # ------------------------------------------------------------------
    # Developer tools
    # ------------------------------------------------------------------
    # Liveness Test Lab API (/api/v1/liveness-test). Off unless explicitly enabled;
    # keep it off in production. When off the router is not mounted (404).
    LIVENESS_TEST_ENABLED: bool = False

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
