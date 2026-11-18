from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _credentials(name: str) -> dict[str, dict]:
    raw = os.getenv(name, "{}")
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        parsed = {}
        for token, item in value.items():
            if not token or not isinstance(item, dict):
                continue
            required = ("use_case", "producer") if "PRODUCER" in name else ("actor_id", "use_cases")
            if any(key not in item for key in required):
                raise ValueError
            if "PRODUCER" not in name and not isinstance(item["use_cases"], list):
                raise ValueError
            if "PRODUCER" not in name and "branch_ids" in item and not isinstance(item["branch_ids"], list):
                raise ValueError
            parsed[str(token)] = item
        return parsed
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"{name} must be a JSON object") from None


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("ALERT_DATABASE_URL", "sqlite:///./alert_service.db"))
    producer_credentials: dict[str, dict] = field(default_factory=lambda: _credentials("ALERT_PRODUCER_CREDENTIALS"))
    operator_credentials: dict[str, dict] = field(default_factory=lambda: _credentials("ALERT_OPERATOR_CREDENTIALS"))
    notification_webhook_url: str = field(default_factory=lambda: os.getenv("ALERT_NOTIFICATION_WEBHOOK_URL", ""))
    notification_poll_seconds: float = field(default_factory=lambda: float(os.getenv("ALERT_NOTIFICATION_POLL_SECONDS", "2")))
    notification_max_attempts: int = field(default_factory=lambda: int(os.getenv("ALERT_NOTIFICATION_MAX_ATTEMPTS", "8")))
    smtp_enabled: bool = field(default_factory=lambda: _boolean("SMTP_ENABLED", False))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_username: str = field(default_factory=lambda: os.getenv("SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""), repr=False)
    smtp_from_email: str = field(default_factory=lambda: os.getenv("SMTP_FROM_EMAIL", ""))
    smtp_from_name: str = field(default_factory=lambda: os.getenv("SMTP_FROM_NAME", "Fedbank Security Alerts"))
    smtp_use_tls: bool = field(default_factory=lambda: _boolean("SMTP_USE_TLS", True))
    smtp_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("SMTP_TIMEOUT_SECONDS", "15")))
    platform_database_path: str = field(default_factory=lambda: os.getenv(
        "FEDBANK_PLATFORM_DB_PATH", str(Path(__file__).resolve().parents[2] / "platform_data" / "platform.db")))


settings = Settings()
