from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from grill_gate_monitoring.models.event import GrillGateEvent
from grill_gate_monitoring.services.event_writer import GrillGateEventWriter


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
    assert rows[0].metadata_json["gate_state"] == "OPEN"
    engine.dispose()


def test_persistence_failure_is_logged_without_stopping_writer(caplog):
    def broken_session():
        raise RuntimeError("database unavailable")

    writer = GrillGateEventWriter(broken_session)
    writer.start()
    writer.submit({"event_type": "MESH_PERSON_EXITED"})
    writer.stop()
    assert "Grill Gate event persistence failed" in caplog.text
    assert writer.submit({"event_type": "MESH_PERSON_ENTERED"}) is False


def test_uploaded_video_event_persists_job_scope_without_fake_camera_assignment():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GrillGateEvent.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    writer = GrillGateEventWriter(factory)
    writer.start()
    assert writer.submit({"event_type": "CROSSING_COMPLETED", "camera_id": "job-id",
        "assignment_id": "job-id", "source_type": "UPLOADED_VIDEO",
        "video_job_id": "00000000-0000-0000-0000-000000000003",
        "video_time_seconds": 3.25, "template_assignment_id": None,
        "occurred_at": datetime.now(timezone.utc), "metadata": {}})
    assert writer.flush()
    writer.stop()
    with Session(engine) as db:
        row = db.scalar(select(GrillGateEvent))
    assert row.camera_id is None and row.assignment_id is None
    assert row.source_type == "UPLOADED_VIDEO"
    assert row.video_job_id == "00000000-0000-0000-0000-000000000003" and row.video_time_seconds == 3.25
    engine.dispose()
