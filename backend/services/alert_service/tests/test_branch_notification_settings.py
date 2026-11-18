from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.main import create_app
from app.settings import Settings
from migrations.branch_notification_settings_v1 import upgrade


def _client(tmp_path, *, branches=("branch-a", "branch-b"), sender=None):
    platform = tmp_path / "platform.db"
    with sqlite3.connect(platform) as db:
        db.execute("CREATE TABLE branches(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL)")
        db.executemany("INSERT INTO branches VALUES(?,?,?)", [
            ("branch-a", "Branch A", "a@example.invalid"),
            ("branch-b", "Branch B", "b@example.invalid"),
        ])
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'alerts.db').as_posix()}",
        operator_credentials={"operator": {"actor_id": "tester", "use_cases": ["*"], "branch_ids": list(branches)}},
        platform_database_path=str(platform))
    app = create_app(settings, start_notification_worker=False, smtp_sender=sender or (lambda *_a, **_k: None))
    return app


def _upgrade(app):
    with app.state.engine.begin() as connection:
        upgrade(connection)


def _body(**overrides):
    body = {"email_enabled": False, "to_recipients": [], "severity_filters": ["critical", "warning"],
        "use_case_filters": ["branch_exterior", "vault_monitoring"], "include_snapshot": True,
        "include_video_evidence": False, "delivery_mode": "instant"}
    return {**body, **overrides}


def test_migration_is_repeat_safe_and_preserves_existing_alerts(tmp_path):
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alerts (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alerts VALUES ('old-alert')"))
        upgrade(connection)
        upgrade(connection)
        assert inspect(connection).has_table("branch_notification_settings")
        assert connection.execute(text("SELECT id FROM alerts")).scalar_one() == "old-alert"
        columns = {column["name"] for column in inspect(connection).get_columns("branch_notification_settings")}
        assert {"branch_id", "email_enabled", "to_recipients", "severity_filters", "use_case_filters",
                "include_snapshot", "include_video_evidence", "delivery_mode", "created_at", "updated_at", "updated_by"} <= columns
    engine.dispose()


def test_get_returns_disabled_safe_defaults_and_save_load_is_branch_isolated(tmp_path):
    app = _client(tmp_path)
    with TestClient(app) as api:
        _upgrade(app)
        headers = {"Authorization": "Bearer operator"}
        defaults = api.get("/api/v1/branches/branch-a/notifications/settings", headers=headers)
        assert defaults.status_code == 200
        assert defaults.json()["email_enabled"] is False
        assert defaults.json()["to_recipients"] == []
        saved = api.put("/api/v1/branches/branch-a/notifications/settings", headers=headers,
            json=_body(email_enabled=True, to_recipients=[" Sec@example.invalid ", "sec@example.invalid", "manager@example.invalid"]))
        assert saved.status_code == 200
        assert saved.json()["to_recipients"] == ["sec@example.invalid", "manager@example.invalid"]
        assert saved.json()["updated_by"] == "tester"
        api.put("/api/v1/branches/branch-b/notifications/settings", headers=headers,
            json=_body(to_recipients=["b@example.invalid"]))
        assert api.get("/api/v1/branches/branch-a/notifications/settings", headers=headers).json()["to_recipients"] == ["sec@example.invalid", "manager@example.invalid"]
        assert api.get("/api/v1/branches/branch-b/notifications/settings", headers=headers).json()["to_recipients"] == ["b@example.invalid"]
        reloaded = api.get("/api/v1/branches/branch-a/notifications/settings", headers=headers).json()
        assert reloaded["severity_filters"] == ["critical", "warning"]
        assert reloaded["use_case_filters"] == ["branch_exterior", "vault_monitoring"]
        assert reloaded["include_snapshot"] is True and reloaded["include_video_evidence"] is False


def test_invalid_recipients_filters_delivery_and_enabled_without_recipient_are_rejected(tmp_path):
    app = _client(tmp_path)
    with TestClient(app) as api:
        _upgrade(app)
        url = "/api/v1/branches/branch-a/notifications/settings"
        headers = {"Authorization": "Bearer operator"}
        invalids = [
            _body(to_recipients=["invalid"]),
            _body(severity_filters=["urgent"]),
            _body(use_case_filters=["whatsapp"]),
            _body(delivery_mode="hourly"),
            _body(email_enabled=True, to_recipients=[]),
        ]
        for body in invalids:
            assert api.put(url, headers=headers, json=body).status_code == 422


def test_settings_routes_enforce_auth_branch_scope_and_branch_existence(tmp_path):
    app = _client(tmp_path, branches=("branch-a",))
    with TestClient(app) as api:
        _upgrade(app)
        assert api.get("/api/v1/branches/branch-a/notifications/settings").status_code == 401
        headers = {"Authorization": "Bearer operator"}
        assert api.get("/api/v1/branches/branch-b/notifications/settings", headers=headers).status_code == 403
        assert api.get("/api/v1/branches/missing/notifications/settings", headers=headers).status_code == 403


def test_authorized_operator_gets_not_found_for_missing_branch(tmp_path):
    app = _client(tmp_path, branches=("*",))
    with TestClient(app) as api:
        _upgrade(app)
        response = api.get("/api/v1/branches/missing/notifications/settings",
            headers={"Authorization": "Bearer operator"})
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "BRANCH_NOT_FOUND"


def test_save_does_not_send_email_and_test_uses_only_saved_recipients(tmp_path):
    sent = []
    app = _client(tmp_path, sender=lambda settings, **message: sent.append(message))
    with TestClient(app) as api:
        _upgrade(app)
        headers = {"Authorization": "Bearer operator"}
        url = "/api/v1/branches/branch-a/notifications/settings"
        saved = api.put(url, headers=headers, json=_body(email_enabled=True,
            to_recipients=["first@example.invalid", "second@example.invalid"]))
        assert saved.status_code == 200 and sent == []
        response = api.post("/api/v1/branches/branch-a/notifications/email/test", headers=headers,
            json={"recipients": ["attacker@example.invalid"]})
        assert response.status_code == 200
        assert sent[0]["recipients"] == ["first@example.invalid", "second@example.invalid"]
