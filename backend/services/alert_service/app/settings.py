from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


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
            parsed[str(token)] = item
        return parsed
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"{name} must be a JSON object") from None


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("ALERT_DATABASE_URL", "sqlite:///./alert_service.db"))
    producer_credentials: dict[str, dict] = field(default_factory=lambda: _credentials("ALERT_PRODUCER_CREDENTIALS"))
    operator_credentials: dict[str, dict] = field(default_factory=lambda: _credentials("ALERT_OPERATOR_CREDENTIALS"))
    notification_webhook_url: str = field(default_factory=lambda: os.getenv("ALERT_NOTIFICATION_WEBHOOK_URL", ""))
    notification_poll_seconds: float = field(default_factory=lambda: float(os.getenv("ALERT_NOTIFICATION_POLL_SECONDS", "2")))
    notification_max_attempts: int = field(default_factory=lambda: int(os.getenv("ALERT_NOTIFICATION_MAX_ATTEMPTS", "8")))


settings = Settings()
