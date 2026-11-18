from __future__ import annotations

from app.settings import Settings


SMTP_NAMES = (
    "SMTP_ENABLED", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL", "SMTP_FROM_NAME", "SMTP_USE_TLS", "SMTP_TIMEOUT_SECONDS",
)


def test_smtp_is_disabled_and_credentials_are_optional_by_default(monkeypatch):
    for name in SMTP_NAMES:
        monkeypatch.delenv(name, raising=False)

    config = Settings()

    assert config.smtp_enabled is False
    assert config.smtp_host == "smtp.gmail.com"
    assert config.smtp_port == 587
    assert config.smtp_username == ""
    assert config.smtp_password == ""
    assert config.smtp_from_email == ""
    assert config.smtp_from_name == "Fedbank Security Alerts"
    assert config.smtp_use_tls is True
    assert config.smtp_timeout_seconds == 15


def test_smtp_environment_values_load_without_exposing_the_password(monkeypatch):
    values = {
        "SMTP_ENABLED": "true",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "smtp-test@example.invalid",
        "SMTP_PASSWORD": "not-a-real-password",
        "SMTP_FROM_EMAIL": "alerts@example.invalid",
        "SMTP_FROM_NAME": "Security Alerts",
        "SMTP_USE_TLS": "true",
        "SMTP_TIMEOUT_SECONDS": "12.5",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = Settings()

    assert config.smtp_enabled is True
    assert config.smtp_timeout_seconds == 12.5
    assert "not-a-real-password" not in repr(config)
