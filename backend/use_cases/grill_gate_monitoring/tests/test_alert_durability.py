from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import json
import cv2
import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func, delete
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.db.models import RegistryCamera, RegistryLocation, GrillGateVideoJob, VaultAuditEvent
from app.api.dependencies import get_db, get_operator, Operator
from grill_gate_monitoring.models.alert import GrillGateAlert
from grill_gate_monitoring.services.alert_store import persist_command, GrillGateAlertWriter, GrillGateAlertSink
from grill_gate_monitoring.services.alert_delivery import ENTITY, PENDING, DELIVERED, FAILED, backfill_publications
from grill_gate_monitoring.services.alert_publisher import GrillGateAlertPublisher
from grill_gate_monitoring.services.alert_evidence import GrillGateEvidence
from grill_gate_monitoring.services import alert_evidence, alert_store
from grill_gate_monitoring.api import grill_gate

T0 = datetime(2026, 11, 11, tzinfo=timezone.utc)

@pytest.fixture
def h(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'incidents.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[m.__table__ for m in
        (RegistryLocation, RegistryCamera, GrillGateVideoJob, GrillGateAlert, VaultAuditEvent)])
    factory = sessionmaker(engine, expire_on_commit=False)
    evidence = GrillGateEvidence(tmp_path)
    monkeypatch.setattr(alert_evidence, "_evidence", evidence)
    writer = GrillGateAlertWriter(factory)
    app = FastAPI(); app.include_router(grill_gate.router)
    def session():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_operator] = lambda: Operator("test", "Test operator")
    with TestClient(app) as client:
        yield SimpleNamespace(factory=factory, evidence=evidence, writer=writer, client=client, root=tmp_path)
    engine.dispose()

def command(source=None, **changes):
    source = source or str(uuid4())
    value = {"action": "create", "source_event_id": source, "capture_evidence": False,
      "payload": {"source_event_type": "GATE_OPEN_TOO_LONG", "source_event_version": 1,
        "occurred_at": T0.isoformat(), "last_seen_at": T0.isoformat(), "severity": "WARNING",
        "title": "Gate open too long", "summary": "Gate remained open without a crossing",
        "resource_refs": {"assignment_id": str(uuid4())},
        "domain_data": {"configured_threshold_seconds": 4, "gate_open_duration_seconds": 4}}}
    value.update(changes); return value

def saved(h, value):
    assert h.writer.submit(value)
    with h.factory() as db:
        return db.scalar(select(GrillGateAlert).where(GrillGateAlert.source_event_id == value["source_event_id"]))

def test_committed_alert_and_outbox_survive_new_sessions_and_duplicate_evaluations(h):
    value = command(); first = saved(h, value); again = saved(h, value)
    assert first.id == again.id
    with h.factory() as db:
        assert db.scalar(select(func.count()).select_from(GrillGateAlert)) == 1
        assert db.scalar(select(func.count()).select_from(VaultAuditEvent)) == 1
    restarted = GrillGateAlertWriter(h.factory)
    assert restarted.active_conditions(first.assignment_id, "unused") == []
    with h.factory() as db:
        assert db.get(GrillGateAlert, first.id).status == "OPEN"

def test_failed_outbox_staging_rolls_back_the_incident_instead_of_reporting_queue_success(h, monkeypatch):
    monkeypatch.setattr(alert_store, "stage_publication", lambda *args: (_ for _ in ()).throw(RuntimeError("DB unavailable")))
    assert h.writer.submit(command()) is False
    with h.factory() as db:
        assert db.scalar(select(func.count()).select_from(GrillGateAlert)) == 0

def test_sink_has_only_one_publication_boundary(h):
    shared = SimpleNamespace(submit=lambda _: pytest.fail("duplicate fan-out"))
    assert GrillGateAlertSink(h.writer, shared).submit(command())

@pytest.mark.parametrize("alert_type", ["GATE_OPEN_TOO_LONG", "GATE_PARTIALLY_OPEN_TOO_LONG", "MESH_OCCUPANCY_LIMIT_EXCEEDED"])
def test_actual_source_snapshot_is_durable_and_retrievable_only_with_matching_source(h, alert_type):
    value = command(capture_evidence=True)
    value["payload"]["source_event_type"] = alert_type
    packet = SimpleNamespace(frame=np.full((24, 32, 3), 73, np.uint8), captured_at=T0,
        video_time_seconds=None, sequence_number=17)
    h.evidence.remember(value["source_event_id"], packet)
    row = saved(h, value); h.writer.capture_pending()
    with h.factory() as db:
        row = db.get(GrillGateAlert, row.id)
        assert row.domain_data["evidence_status"] == "CAPTURED"
        ref = row.evidence_refs[0]
        assert ref["frame_index"] == 17
        assert ref["captured_at"] == T0.isoformat()
        assert "retrieval_path" in ref and str(h.root) not in json.dumps(ref)
    correct = h.client.get(ref["retrieval_path"])
    assert correct.status_code == 200 and correct.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(correct.content, np.uint8), cv2.IMREAD_COLOR)
    assert abs(float(image.mean()) - 73) < 2
    assert h.client.get(ref["retrieval_path"].replace(row.assignment_id, str(uuid4()))).status_code == 404
    assert h.client.get(f"/api/v1/grill-gate/alerts/{row.id}/evidence/{uuid4()}?assignment_id={row.assignment_id}").status_code == 404
    with pytest.raises(ValueError): h.evidence.path("../../secret")
    h.client.app.dependency_overrides.pop(get_operator)
    assert h.client.get(ref["retrieval_path"]).status_code in {401, 503}

def test_capture_failure_never_loses_the_alert_and_historical_evidence_is_unavailable(h):
    row = saved(h, command(capture_evidence=True)); h.writer.capture_pending()
    with h.factory() as db:
        row = db.get(GrillGateAlert, row.id)
        assert row.status == "OPEN" and row.domain_data["evidence_status"] == "UNAVAILABLE"
        delivery = db.scalar(select(VaultAuditEvent))
        assert delivery.details["payload"]["domain_data"]["evidence_status"] == "UNAVAILABLE"
        assert row.evidence_refs == []

def test_uploaded_snapshot_decodes_the_requested_source_time_after_processing(h):
    path = h.root / "source.avi"
    video = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
    assert video.isOpened()
    for index in range(30): video.write(np.full((24, 32, 3), index * 5, np.uint8))
    video.release()
    job_id = str(uuid4())
    with h.factory() as db:
        db.add(GrillGateVideoJob(id=job_id, original_filename="source.avi", storage_path=str(path), status="COMPLETED", config_snapshot={}))
        db.commit()
    value = command(capture_evidence=True)
    value["payload"]["resource_refs"] = {"video_job_id": job_id}
    value["payload"]["domain_data"]["video_time_seconds"] = 1.0
    row = saved(h, value); h.writer.capture_pending()
    with h.factory() as db:
        row = db.get(GrillGateAlert, row.id); ref = row.evidence_refs[0]
        assert abs(ref["video_timestamp_seconds"] - 1.0) < 0.11
    path.unlink()  # retained evidence does not depend on the original source file
    assert h.client.get(ref["retrieval_path"]).status_code == 200

@pytest.mark.parametrize("target,path", [("ACKNOWLEDGED", "acknowledge"), ("RESOLVED", "resolve"), ("DISMISSED", "dismiss")])
def test_manual_status_commits_a_mirrored_transition_without_deleting_incident(h, target, path):
    row = saved(h, command())
    result = h.client.post(f"/api/v1/grill-gate/alerts/{row.id}/{path}", json={"expected_version": 1, "note": "Reviewed by operator"})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == target
    with h.factory() as db:
        assert db.get(GrillGateAlert, row.id) is not None
        changes = db.scalars(select(VaultAuditEvent).where(VaultAuditEvent.entity_type == ENTITY)).all()
        assert len(changes) == 2
        assert any(item.details["payload"]["source_status"] == target for item in changes)
        audit = db.scalar(select(VaultAuditEvent).where(VaultAuditEvent.entity_type == "grill_gate_alert"))
        assert audit.details["actor_id"] == "test" and audit.details["note"] == "Reviewed by operator"
        assert audit.details["from_status"] == "OPEN" and audit.details["to_status"] == target
        assert audit.details["acted_at"]
        if target == "ACKNOWLEDGED":
            assert result.json()["acknowledgement_comment"] == "Reviewed by operator"
            assert result.json()["acknowledged_at"] and result.json()["acknowledged_by"] == "test"
        if target == "DISMISSED":
            assert result.json()["dismissed_at"] and result.json()["resolved_at"] is None

def test_backfill_defaults_to_dry_run_and_is_idempotent(h):
    row = saved(h, command())
    with h.factory() as db:
        db.execute(delete(VaultAuditEvent)); db.commit()
        assert backfill_publications(db)["eligible"] == 1
        assert db.scalar(select(func.count()).select_from(VaultAuditEvent)) == 0
        assert backfill_publications(db, dry_run=False)["eligible"] == 1
        assert backfill_publications(db, dry_run=False)["eligible"] == 0

class Remote:
    def __init__(self, identity="grill_gate", fail=False):
        self.identity, self.fail, self.rows, self.posts = identity, fail, {}, []
    def handle(self, request):
        if request.url.path.endswith("/producer"):
            return httpx.Response(200, json={"use_case": self.identity, "producer": "grill-gate-monitoring"})
        if request.method == "GET":
            row = self.rows.get(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200 if row else 404, json=row or {})
        body = json.loads(request.content)
        if request.method == "POST":
            self.posts.append(request.headers["Idempotency-Key"])
            if self.fail: return httpx.Response(503)
        row = {**body, "id": "common-id"}
        self.rows[body["source_event_id"]] = row
        return httpx.Response(201 if request.method == "POST" else 200, json=row)
    def factory(self, **kwargs): return httpx.Client(transport=httpx.MockTransport(self.handle), **kwargs)

def publisher(h, remote):
    return GrillGateAlertPublisher("http://common.test", "dedicated-secret", session_factory=h.factory, client_factory=remote.factory)

def test_publication_failure_is_durable_and_retried_with_same_identity_after_restart(h):
    row = saved(h, command()); remote = Remote(fail=True)
    publisher(h, remote).drain_database_once()
    with h.factory() as db:
        delivery = db.scalar(select(VaultAuditEvent)); assert delivery.action == PENDING
        assert delivery.details["attempt"] == 1
        delivery.details = {**delivery.details, "due_at": T0.isoformat()}; db.commit()
    remote.fail = False
    publisher(h, remote).drain_database_once()
    assert len(remote.rows) == 1 and len(set(remote.posts)) == 1
    with h.factory() as db: assert db.scalar(select(VaultAuditEvent)).action == DELIVERED
    assert remote.rows[row.source_event_id]["source_status"] == "OPEN"

def test_vault_identity_is_rejected_before_any_common_create(h):
    saved(h, command()); remote = Remote(identity="vault_monitoring")
    publisher(h, remote).drain_database_once()
    assert remote.posts == []
    with h.factory() as db: assert db.scalar(select(VaultAuditEvent)).action == FAILED

def test_legacy_automatic_recovery_does_not_close_a_persisted_incident(h):
    value = command(); row = saved(h, value); remote = Remote()
    publisher(h, remote).drain_database_once()
    assert h.writer.submit({"action": "resolve", "source_event_id": value["source_event_id"], "note": "Gate closed"})
    publisher(h, remote).drain_database_once()
    assert remote.rows[row.source_event_id]["source_status"] == "OPEN"


def test_active_history_filtering_keeps_resolved_rows(h, monkeypatch):
    row = saved(h, command())
    monkeypatch.setattr(grill_gate, "_assignment_camera", lambda *args, **kwargs: None)
    active = f"/api/v1/grill-gate/assignments/{row.assignment_id}/alerts/active"
    history = f"/api/v1/grill-gate/assignments/{row.assignment_id}/alerts/history"
    assert len(h.client.get(active).json()["items"]) == 1
    assert h.client.post(f"/api/v1/grill-gate/alerts/{row.id}/resolve", json={"expected_version": row.row_version, "note": "Operator reviewed the incident"}).status_code == 200
    assert h.client.get(active).json()["items"] == []
    assert len(h.client.get(history).json()["items"]) == 1
    assert h.client.get(f"/api/v1/grill-gate/alerts/{row.id}").json()["status"] == "RESOLVED"


def test_final_video_reconciliation_stages_publication_and_captures_real_evidence(h):
    path = h.root / "final.avi"
    video = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
    assert video.isOpened()
    for index in range(80): video.write(np.full((24, 32, 3), index, np.uint8))
    video.release()
    job_id = str(uuid4())
    with h.factory() as db:
        db.add(GrillGateVideoJob(id=job_id, original_filename="final.avi", storage_path=str(path),
            status="COMPLETED", progress_seconds=6, completed_at=T0, config_snapshot={
                "alert_configuration": {"gate_open_enabled": True, "max_gate_open_seconds": 4},
                "final_status": {"gate_state": "FULLY_OPEN", "open_without_crossing_seconds": 4,
                    "open_without_crossing_threshold_seconds": 4}}))
        db.commit()
    body = {"elapsed_seconds": 4, "threshold_seconds": 4, "timer_cycle_id": f"video:{job_id}:2000",
            "gate_session_id": f"video:{job_id}", "video_timestamp_seconds": 6}
    endpoint = f"/api/v1/grill-gate/videos/{job_id}/alerts/evaluate-open-gate"
    response = h.client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["alert_raised"] is True
    assert h.client.post(endpoint, json=body).json()["alert_id"] == response.json()["alert_id"]
    h.writer.capture_pending()
    with h.factory() as db:
        row = db.get(GrillGateAlert, response.json()["alert_id"])
        assert row.evidence_refs[0]["video_timestamp_seconds"] == 6
        assert db.scalar(select(func.count()).select_from(VaultAuditEvent)) == 1
        assert db.scalar(select(VaultAuditEvent)).details["payload"]["evidence_refs"]


def test_mesh_gap_does_not_report_recovery():
    from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor
    processor = GrillGateFrameProcessor(person_detector=None, tracker=None, event_sink=lambda _: True)
    processor._alerts.on_mesh_occupancy = lambda *args: pytest.fail("gap is not a recovery observation")
    processor.process_gap(now_monotonic=1.0, timestamp=T0)


def test_frontend_timer_snapshot_uses_validated_video_time_not_a_later_packet(h):
    from datetime import timedelta
    from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor
    from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
    path = h.root / "threshold.avi"
    video = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
    assert video.isOpened()
    for index in range(80): video.write(np.full((24, 32, 3), index, np.uint8))
    video.release()
    job_id = str(uuid4())
    with h.factory() as db:
        db.add(GrillGateVideoJob(id=job_id, original_filename="threshold.avi", storage_path=str(path),
            status="PROCESSING", progress_seconds=7, config_snapshot={}))
        db.commit()
    processor = GrillGateFrameProcessor(person_detector=None, tracker=None, event_sink=lambda _: True,
        alert_sink=h.writer.submit, camera_id=job_id, assignment_id=job_id,
        alert_source_context={"source_type": "UPLOADED_VIDEO", "video_job_id": job_id})
    processor._alerts.configure(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=4))
    processor._alerts.on_gate_transition("FULLY_OPEN", T0 + timedelta(seconds=2))
    processor._current_packet = SimpleNamespace(frame=np.full((24, 32, 3), 200, np.uint8), captured_at=T0 + timedelta(seconds=7),
        source_type="UPLOADED_VIDEO", video_time_seconds=7, sequence_number=70)
    result = processor.evaluate_open_gate_alert(4, 4, f"video:{job_id}:2000", 6)
    assert result["alert_raised"] is True
    h.writer.capture_pending()
    with h.factory() as db:
        row = db.scalar(select(GrillGateAlert)); ref = row.evidence_refs[0]
        assert ref["video_timestamp_seconds"] == 6
        response = h.client.get(ref["retrieval_path"])
        image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        assert abs(float(image.mean()) - 60) < 3, 'snapshot must be decoded at 6s, not the later gray-200 packet'


def test_non_timer_incident_retry_keeps_original_payload_and_source_id():
    from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine
    from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
    from datetime import timedelta
    commands = []
    rule = GrillGateAlertRuleEngine("cam", "assignment", lambda c: commands.append(c) or False,
        config=GrillGateAlertConfig(mesh_occupancy_enabled=True, max_mesh_occupancy=1))
    rule.on_mesh_occupancy(2, T0)
    rule.on_mesh_occupancy(3, T0 + timedelta(seconds=2))
    assert commands[0] == commands[1]
    assert datetime.fromisoformat(commands[0]["payload"]["occurred_at"].replace("Z", "+00:00")) == T0


def test_snapshot_sidecar_recovers_after_file_write_before_database_commit(h):
    value = command(capture_evidence=True)
    h.evidence.remember(value["source_event_id"], SimpleNamespace(frame=np.full((24, 32, 3), 88, np.uint8),
        captured_at=T0, video_time_seconds=None, sequence_number=1))
    row = saved(h, value)
    with h.factory() as db:
        ref = h.evidence.capture(db, db.get(GrillGateAlert, row.id))
        db.rollback()
    restarted = GrillGateEvidence(h.root)
    with h.factory() as db:
        recovered = restarted.capture(db, db.get(GrillGateAlert, row.id))
    assert recovered == ref


def test_missing_mesh_track_does_not_resolve_until_confirmed_observation_returns():
    from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor
    from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
    sent = []
    processor = GrillGateFrameProcessor(person_detector=None, tracker=None, event_sink=lambda _: True,
        alert_sink=lambda command: sent.append(command) or True)
    processor._alerts.configure(GrillGateAlertConfig(mesh_occupancy_enabled=True, max_mesh_occupancy=0))
    snapshot = {"occupied_track_ids": [1], "occupancy_count": 1}
    processor._mesh.status = lambda: snapshot
    processor._apply_mesh_alert_observation([{"track_id": 1, "confidence": 1}], T0)
    assert [item["action"] for item in sent] == ["create"]
    snapshot = {"occupied_track_ids": [], "occupancy_count": 0}
    processor._apply_mesh_alert_observation([], T0)
    assert [item["action"] for item in sent] == ["create"]
    processor._apply_mesh_alert_observation([{"track_id": 1, "confidence": 1}], T0)
    assert [item["action"] for item in sent] == ["create"]


@pytest.mark.parametrize("recovery", ["gate_closed", "crossing_reset", "video_completed"])
def test_condition_recovery_and_completion_keep_persisted_incident_open(h, recovery):
    from datetime import timedelta
    from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
    from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine
    rule = GrillGateAlertRuleEngine(str(uuid4()), str(uuid4()), h.writer.submit,
        config=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3))
    rule.on_crossing_activity(0, True, T0)
    rule.on_gate_transition("OPEN", T0)
    rule.tick(T0 + timedelta(seconds=3))
    with h.factory() as db:
        before = db.scalar(select(GrillGateAlert))
        identity = before.id
    if recovery == "gate_closed": rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=4))
    elif recovery == "crossing_reset": rule.on_crossing_activity(1, True, T0 + timedelta(seconds=4))
    else: rule.reset()
    with h.factory() as db:
        row = db.get(GrillGateAlert, identity)
        assert row.status == "OPEN" and row.row_version == 1 and row.resolved_at is None
        assert db.scalar(select(func.count()).select_from(GrillGateAlert)) == 1


def test_action_audit_and_outbox_are_atomic_and_stale_retries_do_not_duplicate(h, monkeypatch):
    row = saved(h, command())
    original = grill_gate.stage_publication
    monkeypatch.setattr(grill_gate, "stage_publication", lambda *args: (_ for _ in ()).throw(RuntimeError("outbox unavailable")))
    with pytest.raises(RuntimeError):
        h.client.post(f"/api/v1/grill-gate/alerts/{row.id}/acknowledge", json={"expected_version":1,"note":"Checked snapshot"})
    with h.factory() as db:
        assert db.get(GrillGateAlert, row.id).status == "OPEN"
        assert db.scalar(select(func.count()).select_from(VaultAuditEvent).where(VaultAuditEvent.entity_type == "grill_gate_alert")) == 0
    monkeypatch.setattr(grill_gate, "stage_publication", original)
    url = f"/api/v1/grill-gate/alerts/{row.id}/acknowledge"
    body = {"expected_version":1,"note":"  Checked snapshot  "}
    assert h.client.post(url, json=body).status_code == 200
    assert h.client.post(url, json=body).status_code == 409
    stored = h.client.get(f"/api/v1/grill-gate/alerts/{row.id}").json()
    assert stored["acknowledgement_comment"] == "Checked snapshot"
    with h.factory() as db:
        assert db.scalar(select(func.count()).select_from(VaultAuditEvent).where(VaultAuditEvent.entity_type == "grill_gate_alert")) == 1
