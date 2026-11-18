from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.smtp_client import SmtpDeliveryError, send_email
from app.settings import Settings


def platform_database(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE branches(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL)")
        db.executemany("INSERT INTO branches VALUES(?,?,?)", [
            ("branch-1", "Chennai B1", "chennai@example.invalid"),
            ("branch-2", "South City", "south@example.invalid"),
            ("branch-empty", "No Email", ""),
        ])


def client(tmp_path, *, sender, branches=("branch-1",), smtp_enabled=True, smtp_password="fake"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    platform = tmp_path / "platform.db"
    platform_database(platform)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'alerts.db').as_posix()}",
        operator_credentials={"operator": {"actor_id": "tester", "use_cases": ["*"],
                                            "branch_ids": list(branches)}},
        platform_database_path=str(platform), smtp_enabled=smtp_enabled,
        smtp_username="sender@example.invalid", smtp_password=smtp_password,
        smtp_from_email="sender@example.invalid")
    return TestClient(create_app(settings, start_notification_worker=False, smtp_sender=sender))


def test_authenticated_test_email_uses_only_backend_branch_recipient(tmp_path):
    sent = []
    def sender(settings, **message): sent.append(message)
    with client(tmp_path, sender=sender) as api:
        response = api.post("/api/v1/branches/branch-1/notifications/email/test",
                            headers={"Authorization": "Bearer operator"},
                            json={"recipients": ["attacker@example.invalid"]})
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert sent[0]["recipients"] == ["chennai@example.invalid"]
    assert sent[0]["subject"] == "[Fedbank] Email Notification Test — Chennai B1"
    assert "No security incident has occurred" in sent[0]["body"]


def test_test_email_requires_authentication_and_branch_authorization(tmp_path):
    with client(tmp_path, sender=lambda *_args, **_kwargs: None) as api:
        assert api.post("/api/v1/branches/branch-1/notifications/email/test").status_code == 401
        forbidden = api.post("/api/v1/branches/branch-2/notifications/email/test",
                             headers={"Authorization": "Bearer operator"})
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "BRANCH_FORBIDDEN"


def test_cross_branch_recipient_isolation_for_authorized_wildcard_operator(tmp_path):
    sent = []
    with client(tmp_path, sender=lambda settings, **message: sent.append(message), branches=("*",)) as api:
        response = api.post("/api/v1/branches/branch-2/notifications/email/test",
                            headers={"Authorization": "Bearer operator"})
    assert response.status_code == 200
    assert sent[0]["recipients"] == ["south@example.invalid"]


def test_missing_recipient_is_rejected_before_smtp(tmp_path):
    called = False
    def sender(*_args, **_kwargs):
        nonlocal called; called = True
    with client(tmp_path, sender=sender, branches=("*",)) as api:
        response = api.post("/api/v1/branches/branch-empty/notifications/email/test",
                            headers={"Authorization": "Bearer operator"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "RECIPIENT_NOT_CONFIGURED"
    assert called is False


def test_disabled_and_missing_smtp_configuration_never_connect(tmp_path):
    for enabled, password, expected in [(False, "fake", "SMTP_DISABLED"), (True, "", "SMTP_NOT_CONFIGURED")]:
        with client(tmp_path / ("off" if not enabled else "missing"), sender=send_email,
                    smtp_enabled=enabled, smtp_password=password) as api:
            response = api.post("/api/v1/branches/branch-1/notifications/email/test",
                                headers={"Authorization": "Bearer operator"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == expected


def test_smtp_failure_is_sanitized_and_rate_limit_prevents_duplicate_send(tmp_path):
    def authentication_failure(*_args, **_kwargs):
        raise SmtpDeliveryError("authentication_failed", "Gmail rejected the configured SMTP credentials")
    with client(tmp_path / "failure", sender=authentication_failure) as api:
        failed = api.post("/api/v1/branches/branch-1/notifications/email/test",
                          headers={"Authorization": "Bearer operator"})
    assert failed.status_code == 422
    assert failed.json()["detail"]["code"] == "SMTP_AUTHENTICATION_FAILED"

    calls = []
    with client(tmp_path / "limit", sender=lambda settings, **message: calls.append(message)) as api:
        first = api.post("/api/v1/branches/branch-1/notifications/email/test",
                         headers={"Authorization": "Bearer operator"})
        second = api.post("/api/v1/branches/branch-1/notifications/email/test",
                          headers={"Authorization": "Bearer operator"})
    assert first.status_code == 200 and second.status_code == 429
    assert len(calls) == 1
