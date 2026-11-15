import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.main import create_app
from app.settings import Settings
from test_alert_api import payload


@pytest.mark.skipif(not os.getenv("ALERT_TEST_DATABASE_URL"),
                    reason="requires an isolated PostgreSQL test database")
def test_all_new_producers_persist_in_postgres_with_identity_and_evidence():
    database_url = os.environ["ALERT_TEST_DATABASE_URL"]
    producers = {
        "vault-token": {"use_case": "vault_monitoring", "producer": "vault-monitoring"},
        "gate-token": {"use_case": "grill_gate", "producer": "grill-gate-monitoring"},
        "branch-token": {"use_case": "branch_exterior", "producer": "branch-exterior-monitoring"},
        "face-token": {"use_case": "face_mask", "producer": "face-mask-monitoring"},
    }
    settings = Settings(database_url=database_url, producer_credentials=producers,
        operator_credentials={"operator-token": {"actor_id": "test", "use_cases": ["*"]}},
        notification_webhook_url="")
    app = create_app(settings, start_notification_worker=False)
    prefix = f"postgres-{uuid4()}"
    cases = [
        ("vault-token", "vault", "CAMERA_FEED_LOST", "WARNING"),
        ("gate-token", "gate", "GATE_OPEN_TOO_LONG", "WARNING"),
        ("gate-token", "mesh", "MESH_OCCUPANCY_LIMIT_EXCEEDED", "WARNING"),
        ("branch-token", "branch", "movement", "medium"),
        ("face-token", "face", "FACE_CONCEALMENT", "WARNING"),
    ]
    created = {}
    bodies = {}
    visible_metadata = {"branch_code": "C99127-01", "branch_name": "Configured branch", "camera_name": "Configured camera",
        "place_name": "Bengaluru", "region_name": "South", "branch_manager": "Configured manager"}
    with TestClient(app) as client:
        assert {"alerts", "alert_idempotency", "alert_audit", "notification_outbox"}.issubset(
            set(inspect(app.state.engine).get_table_names()))
        for token, label, event_type, severity in cases:
            source_id = f"{prefix}-{label}"
            metadata = visible_metadata if label in {"vault", "gate"} else {}
            source_refs = ({"branch_id": "branch-1", "video_job_id": "uploaded-job-1"}
                if label == "gate" else {"branch_id": "branch-1", "camera_id": "camera-1"})
            body = payload(source_event_id=source_id, source_event_type=event_type,
                severity=severity, resource_refs=source_refs,
                evidence_refs=[{"provider": label, "id": "snapshot-1", "type": "snapshot"}])
            body["resource_refs"].update(metadata)
            if label == "gate":
                body["domain_data"].update(source_type="UPLOADED_VIDEO", video_filename="gate.mp4")
            headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": source_id}
            response = client.post("/api/v1/alerts", headers=headers, json=body)
            assert response.status_code == 201
            created[label] = response.json()
            bodies[label] = body
            replay = client.post("/api/v1/alerts", headers=headers, json=body)
            assert replay.status_code == 200
            assert replay.json()["id"] == created[label]["id"]
            assert replay.json()["resource_refs"] == body["resource_refs"]
            assert replay.json()["evidence_refs"] == body["evidence_refs"]

        resolution = client.put(f"/api/v1/alerts/source-events/{prefix}-vault",
            headers={"Authorization": "Bearer vault-token", "If-Match": "1"},
            json={**bodies["vault"], "source_event_version": 2, "source_status": "RESOLVED",
                "domain_data": {**bodies["vault"]["domain_data"],
                    "lifecycle_actor_type": "operator", "lifecycle_actor_id": "test-operator"}})
        assert resolution.status_code == 200
        assert resolution.json()["id"] == created["vault"]["id"]
        assert resolution.json()["status"] == "RESOLVED"

        listed = client.get("/api/v1/alerts?limit=100",
            headers={"Authorization": "Bearer operator-token"})
        assert listed.status_code == 200
        rows = [item for item in listed.json()["items"] if item["source_event_id"].startswith(prefix)]
        assert len(rows) == 5
        assert {item["use_case"] for item in rows} == {
            "vault_monitoring", "grill_gate", "branch_exterior", "face_mask"}
        gate = next(item for item in rows if item["source_event_id"] == f"{prefix}-gate")
        for label in ("vault", "gate"):
            row = next(item for item in rows if item["source_event_id"] == f"{prefix}-{label}")
            detail = client.get(f"/api/v1/alerts/{row['id']}",
                headers={"Authorization": "Bearer operator-token"})
            assert detail.status_code == 200
            for key in ("branch_code", "branch_name", "camera_name", "place_name", "region_name", "branch_manager"):
                assert row[key] == detail.json()[key] == visible_metadata[key]
        assert gate["video_job_id"] == detail.json()["video_job_id"] == "uploaded-job-1"
        assert gate["camera_id"] is None and detail.json()["camera_id"] is None
        for use_case, label in (("vault_monitoring", "vault"), ("grill_gate", "gate")):
            row = created[label]
            matching = client.get("/api/v1/alerts",
                params={"use_case": use_case, "branch_id": "branch-1", "limit": 100},
                headers={"Authorization": "Bearer operator-token"})
            different = client.get("/api/v1/alerts",
                params={"use_case": use_case, "branch_id": "branch-2", "limit": 100},
                headers={"Authorization": "Bearer operator-token"})
            cleared = client.get("/api/v1/alerts", params={"use_case": use_case, "limit": 100},
                headers={"Authorization": "Bearer operator-token"})
            assert row["id"] in {item["id"] for item in matching.json()["items"]}
            assert row["id"] not in {item["id"] for item in different.json()["items"]}
            assert row["id"] in {item["id"] for item in cleared.json()["items"]}
