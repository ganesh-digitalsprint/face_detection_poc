from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from grill_gate_monitoring.models.event import GrillGateEvent
from grill_gate_monitoring.models.alert import GrillGateAlert
from grill_gate_monitoring.services.event_writer import GrillGateEventWriter
from grill_gate_monitoring.services.alert_store import GrillGateAlertSink, GrillGateAlertWriter


def test_crossing_and_mesh_events_are_persisted_as_grill_gate_rows():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GrillGateEvent.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    writer = GrillGateEventWriter(factory)
    writer.start()
    at = datetime.now(timezone.utc)
    assert writer.submit({"event_type": "CROSSING_COMPLETED", "camera_id": "00000000-0000-0000-0000-000000000001",
                          "assignment_id": "00000000-0000-0000-0000-000000000002", "track_id": 7,
                          "direction": "OUTSIDE_TO_INSIDE", "source_zone": "gate_approach",
                          "destination_zone": "gate_interior", "occurred_at": at,
                          "metadata": {"gate_state": "OPEN"}})
    assert writer.submit({"event_type": "MESH_PERSON_ENTERED", "camera_id": "00000000-0000-0000-0000-000000000001",
                          "assignment_id": "00000000-0000-0000-0000-000000000002", "track_id": 7,
                          "occurred_at": at, "metadata": {"zone": "mesh_area"}})
    writer.stop()
    with Session(engine) as db:
        rows = db.scalars(select(GrillGateEvent).order_by(GrillGateEvent.event_type)).all()
    assert [row.event_type for row in rows] == ["CROSSING_COMPLETED", "MESH_PERSON_ENTERED"]
    assert rows[0].direction == "OUTSIDE_TO_INSIDE"
    assert rows[0].track_id == 7
    assert rows[0].camera_id == "00000000-0000-0000-0000-000000000001"
    assert rows[0].assignment_id == "00000000-0000-0000-0000-000000000002"
    assert rows[0].source_zone == "gate_approach" and rows[0].destination_zone == "gate_interior"
    assert rows[0].occurred_at.replace(tzinfo=timezone.utc) == at
    assert rows[0].metadata_json["gate_state"] == "OPEN"
    engine.dispose()


def test_rule_alert_commands_are_durable_deduplicated_and_resolved_locally(tmp_path):
    database = tmp_path / "grill-gate-alerts.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    Base.metadata.create_all(engine, tables=[GrillGateAlert.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    event_id = "episode-1"
    at = datetime(2026, 11, 9, tzinfo=timezone.utc)
    command = {"action": "create", "source_event_id": event_id, "payload": {
        "source_event_type": "GATE_OPEN_WITHOUT_CROSSING", "severity": "WARNING", "title": "Gate open without a crossing",
        "summary": "Gate remained open", "occurred_at": at.isoformat(), "last_seen_at": at.isoformat(),
        "resource_refs": {"assignment_id": "00000000-0000-0000-0000-000000000002"},
        "domain_data": {"condition_since": at.isoformat(), "gate_open_duration_seconds": 12.5,
                        "configured_threshold_seconds": 10.0}}}
    writer = GrillGateAlertWriter(factory)
    writer.start()
    sink = GrillGateAlertSink(writer)
    assert sink.submit(command)
    assert sink.submit(command)  # retried delivery for the same rule-engine episode
    assert sink.flush()
    assert sink.submit({"action": "resolve", "source_event_id": event_id, "resolved_at": at.isoformat(),
                        "note": "Gate closed"})
    assert sink.flush()
    writer.stop()

    # A new writer sees persisted state after process recreation.
    restarted = GrillGateAlertWriter(factory)
    assert restarted.active_conditions("00000000-0000-0000-0000-000000000002", "") == []
    with Session(engine) as db:
        rows = db.scalars(select(GrillGateAlert)).all()
        assert len(rows) == 1
        assert rows[0].status == "RESOLVED" and rows[0].resolution_note == "Gate closed"
        assert rows[0].gate_open_duration_seconds == 12.5
        assert rows[0].configured_threshold_seconds == 10
    engine.dispose()


def test_shared_fanout_failure_does_not_block_local_alert_enqueue(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alerts.sqlite'}")
    Base.metadata.create_all(engine, tables=[GrillGateAlert.__table__])
    writer = GrillGateAlertWriter(sessionmaker(engine, expire_on_commit=False))
    writer.start()

    class UnavailablePublisher:
        def submit(self, _command):
            raise RuntimeError("shared service down")

    sink = GrillGateAlertSink(writer, UnavailablePublisher())
    now = datetime.now(timezone.utc)
    assert sink.submit({"action": "create", "source_event_id": "independent-event", "payload": {
        "source_event_type": "GATE_OPEN_WITHOUT_CROSSING", "occurred_at": now.isoformat(),
        "resource_refs": {}, "domain_data": {}}})
    assert writer.flush()
    writer.stop()
    with Session(engine) as db:
        assert db.scalar(select(GrillGateAlert).where(GrillGateAlert.source_event_id == "independent-event"))
    engine.dispose()


def test_persistence_failure_is_logged_without_stopping_writer(caplog):
    def broken_session():
        raise RuntimeError("database unavailable")

    writer = GrillGateEventWriter(broken_session)
    writer.start()
    writer.submit({"event_type": "MESH_PERSON_EXITED"})
    writer.stop()
    assert "Grill Gate event persistence failed" in caplog.text
    assert '"diagnostic":"event_persistence_failed"' in caplog.text
    assert '"exception_type":"RuntimeError"' in caplog.text
    assert writer.submit({"event_type": "MESH_PERSON_ENTERED"}) is False


def test_uploaded_video_event_persists_job_scope_without_fake_camera_assignment(caplog):
    caplog.set_level("INFO", logger="grill_gate_monitoring.services.event_writer")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GrillGateEvent.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    writer = GrillGateEventWriter(factory)
    writer.start()
    at = datetime.now(timezone.utc)
    assert writer.submit({"event_type": "CROSSING_COMPLETED", "camera_id": "job-id",
        "assignment_id": "job-id", "source_type": "UPLOADED_VIDEO",
        "video_job_id": "00000000-0000-0000-0000-000000000003",
        "video_time_seconds": 3.25, "template_assignment_id": None,
        "track_id": 12, "direction": "INSIDE_TO_OUTSIDE", "source_zone": "gate_interior",
        "destination_zone": "gate_approach", "occurred_at": at,
        "metadata": {"frame_sequence": 41}})
    assert writer.flush()
    writer.stop()
    with Session(engine) as db:
        row = db.scalar(select(GrillGateEvent))
    assert row.camera_id is None and row.assignment_id is None
    assert row.source_type == "UPLOADED_VIDEO"
    assert row.video_job_id == "00000000-0000-0000-0000-000000000003" and row.video_time_seconds == 3.25
    assert row.track_id == 12 and row.direction == "INSIDE_TO_OUTSIDE"
    assert row.source_zone == "gate_interior" and row.destination_zone == "gate_approach"
    assert row.template_assignment_id is None
    assert row.occurred_at.replace(tzinfo=timezone.utc) == at
    assert row.metadata_json["frame_sequence"] == 41
    assert '"diagnostic":"event_persisted"' in caplog.text
    assert f'"event_id":"{row.id}"' in caplog.text
    assert '"video_timestamp":3.25' in caplog.text
    engine.dispose()
