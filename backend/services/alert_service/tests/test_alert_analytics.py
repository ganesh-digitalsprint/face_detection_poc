from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.db.models import Alert
from app.main import create_app
from app.settings import Settings


OPERATOR = "Bearer analytics-operator"


def _alert(*, use_case, at, status, severity, refs=None, source_event_id):
    occurred_at = datetime.fromisoformat(at.replace("Z", "+00:00"))
    return Alert(
        use_case=use_case,
        producer=f"{use_case}-producer",
        source_event_id=source_event_id,
        source_event_type="synthetic_event",
        source_event_version=1,
        category="security",
        severity=severity,
        source_severity=severity,
        title="Synthetic analytics fixture",
        summary="Isolated test row",
        status=status,
        occurred_at=occurred_at,
        first_seen_at=occurred_at,
        last_seen_at=occurred_at,
        received_at=occurred_at,
        updated_at=occurred_at,
        resource_refs=refs or {},
        domain_data={},
        evidence_refs=[],
    )


def _client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'analytics.db').as_posix()}",
        operator_credentials={"analytics-operator": {
            "actor_id": "analytics-test", "use_cases": ["*"], "branch_ids": ["*"]}},
    )
    app = create_app(settings, start_notification_worker=False)
    return app, TestClient(app)


def test_summary_includes_filtered_graph_aggregations_and_unassigned_branch(tmp_path):
    app, client = _client(tmp_path)
    with client:
        with app.state.session_factory() as db:
            db.add_all([
                _alert(use_case="vault_monitoring", at="2026-01-01T02:00:00Z", status="OPEN",
                       severity="HIGH", refs={"branch_id": "branch-1", "branch_name": "Central",
                           "branch_code": "C001"}, source_event_id="a1"),
                _alert(use_case="grill_gate", at="2026-01-01T09:30:00Z", status="ACKNOWLEDGED",
                       severity="WARNING", refs={"branch_id": "branch-1", "branch_name": "Central",
                           "branch_code": "C001"}, source_event_id="a2"),
                _alert(use_case="grill_gate", at="2026-01-02T11:00:00Z", status="RESOLVED",
                       severity="CRITICAL", refs={}, source_event_id="a3"),
                _alert(use_case="branch_exterior", at="2026-01-03T14:00:00Z", status="DISMISSED",
                       severity="INFO", refs={"branch_id": "branch-2", "branch_name": "North",
                           "branch_code": "N002"}, source_event_id="a4"),
                _alert(use_case="face_mask", at="2026-01-03T18:00:00Z", status="OPEN",
                       severity="HIGH", refs={"branch_name": "Unlinked label"}, source_event_id="a5"),
            ])
            db.commit()

        response = client.get("/api/v1/alerts/summary", headers={"Authorization": OPERATOR})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert body["by_status"] == {"OPEN": 2, "ACKNOWLEDGED": 1, "RESOLVED": 1, "DISMISSED": 1}
        assert body["by_severity"] == {"INFO": 1, "WARNING": 1, "HIGH": 2, "CRITICAL": 1}
        assert body["by_day"] == [
            {"date": "2026-01-01", "count": 2},
            {"date": "2026-01-02", "count": 1},
            {"date": "2026-01-03", "count": 2},
        ]
        assert body["by_use_case"] == [
            {"use_case": "grill_gate", "count": 2},
            {"use_case": "branch_exterior", "count": 1},
            {"use_case": "face_mask", "count": 1},
            {"use_case": "vault_monitoring", "count": 1},
        ]
        assert body["by_branch"] == [
            {"branch_id": "branch-1", "branch_name": "Central", "branch_code": "C001", "count": 2},
            {"branch_id": None, "branch_name": "Unassigned", "branch_code": None, "count": 2},
            {"branch_id": "branch-2", "branch_name": "North", "branch_code": "N002", "count": 1},
        ]


def test_summary_graph_aggregations_follow_supported_filters(tmp_path):
    app, client = _client(tmp_path)
    with client:
        with app.state.session_factory() as db:
            db.add_all([
                _alert(use_case="grill_gate", at="2026-02-05T12:00:00Z", status="OPEN",
                       severity="WARNING", refs={"branch_id": "branch-1", "branch_name": "Central"},
                       source_event_id="matching"),
                _alert(use_case="grill_gate", at="2026-02-06T12:00:00Z", status="ACKNOWLEDGED",
                       severity="WARNING", refs={"branch_id": "branch-1", "branch_name": "Central"},
                       source_event_id="wrong-status"),
                _alert(use_case="vault_monitoring", at="2026-02-05T12:00:00Z", status="OPEN",
                       severity="WARNING", refs={"branch_id": "branch-1", "branch_name": "Central"},
                       source_event_id="wrong-use-case"),
                _alert(use_case="grill_gate", at="2026-02-05T12:00:00Z", status="OPEN",
                       severity="WARNING", refs={"branch_id": "branch-2", "branch_name": "North"},
                       source_event_id="wrong-branch"),
            ])
            db.commit()

        response = client.get("/api/v1/alerts/summary", headers={"Authorization": OPERATOR}, params={
            "branch_id": "branch-1", "use_case": "grill_gate", "severity": "WARNING", "status": "OPEN",
            "from": "2026-02-05T00:00:00Z", "to": "2026-02-05T23:59:59Z",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["by_day"] == [{"date": "2026-02-05", "count": 1}]
        assert body["by_use_case"] == [{"use_case": "grill_gate", "count": 1}]
        assert body["by_branch"] == [
            {"branch_id": "branch-1", "branch_name": "Central", "branch_code": None, "count": 1}
        ]

