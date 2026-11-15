from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import VaultAlertCondition, VaultRoomAlert
from app.services.person_detector import Detection, RfDetrPersonDetector
from app.services.vault_alert_persistence import PersistentAlertWorker, SnapshotJob
from app.services.vault_alert_rules import AlertSnapshot, evaluate
from app.services.vault_room_manager import VaultRoomManager
from app.services.vault_room_replay import ReplayAlertSink


def detector_config():
    return SimpleNamespace(
        detector=SimpleNamespace(model="rfdetr-nano", confidence=.5, min_box_area_ratio=.01,
            weights_path=None, device=None, cpu_threads=1, inference_resolution=None),
        mobile_phone=SimpleNamespace(enabled=True, confidence_threshold=.4,
            confirmation_seconds=1., clear_seconds=2., absence_gap_seconds=1.5))


def test_rfdetr_extracts_phone_without_changing_person_threshold_or_tracking_input():
    detector = RfDetrPersonDetector(detector_config())
    detector._cell_phone_class_id = 77
    result = SimpleNamespace(xyxy=np.array([[0, 0, 50, 90], [5, 5, 30, 50], [60, 10, 75, 40]]),
        class_id=np.array([1, 1, 77]), confidence=np.array([.8, .45, .4]),
        data={"class_name": np.array(["person", "person", "cell phone"], dtype=object)})
    persons, phones, stats = detector._select_objects(result, 100, 100)
    assert len(persons) == 1 and persons[0].confidence == .8
    assert len(phones) == 1 and phones[0].class_id == 77 and phones[0].confidence == .4
    assert stats["persons"] == 1 and stats["phones"] == 1


def test_phone_confidence_threshold_and_verified_coco_id_fallback():
    detector = RfDetrPersonDetector(detector_config())
    detector._cell_phone_class_id = 77
    result = SimpleNamespace(xyxy=np.array([[1, 2, 8, 10], [2, 3, 9, 11]]),
        class_id=np.array([77, 77]), confidence=np.array([.399, .401]), data={})
    _persons, phones, _stats = detector._select_objects(result, 20, 20)
    assert [round(item.confidence, 3) for item in phones] == [.401]


def test_installed_coco_mapping_and_person_only_capability_status():
    from rfdetr.assets.coco_classes import COCO_CLASS_NAMES
    detector = RfDetrPersonDetector(detector_config())
    detector._configure_mobile_phone_capability(SimpleNamespace(class_names=COCO_CLASS_NAMES))
    assert detector.status["mobile_phone_supported"] is True
    assert detector._cell_phone_class_id == 77
    detector._configure_mobile_phone_capability(SimpleNamespace(class_names=["person"]))
    assert detector.status["mobile_phone_supported"] is False
    assert detector.status["mobile_phone_reason"] == "class_not_available"


def test_phone_mapping_failure_does_not_disable_class_name_detection(monkeypatch):
    from rfdetr.assets import coco_classes
    detector = RfDetrPersonDetector(detector_config())
    monkeypatch.setattr(coco_classes, "COCO_CLASSES", {1: "person"})
    detector._configure_mobile_phone_capability(
        SimpleNamespace(class_names=coco_classes.COCO_CLASS_NAMES))
    assert detector.status["status"] == "loading"
    assert detector.status["mobile_phone_supported"] is True
    assert detector.status["mobile_phone_reason"] == "class_mapping_error:StopIteration"
    assert detector._cell_phone_class_id is None


class CaptureWorker:
    def __init__(self): self.jobs = []
    def submit(self, snapshot, **kwargs): self.jobs.append((snapshot, kwargs)); return True
    def stop(self, _timeout=5): pass


def manager_with_capture():
    manager = VaultRoomManager(config=SimpleNamespace(entry_buffer_seconds=2, session_seconds=4,
        warn_before_expiry_seconds=1, expired_repeat_seconds=2))
    manager._mobile_phone = SimpleNamespace(enabled=True, confidence_threshold=.4,
        confirmation_seconds=1., clear_seconds=2., absence_gap_seconds=1.5)
    manager._alert_worker = CaptureWorker()
    manager._phase = "VAULT_SESSION"
    manager._session_ref = "session-1"
    manager._access_session_contexts["session-1"] = {
        "branch_id": "branch-1", "branch_code": "C99127-01", "branch_name": "Koramangala",
        "place_name": "Bengaluru", "region_name": "South", "branch_manager": "Manager"}
    manager.bind_camera_source("camera-1", source_type="rtsp", camera_name="Vault Room Camera")
    return manager


def phone(confidence=.8):
    return Detection(10, 20, 30, 50, confidence, 77, "cell phone")


def test_temporal_confirmation_clear_reappearance_and_immutable_attribution():
    manager = manager_with_capture()
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    manager._observe_mobile_phones_locked("camera-1", 0., (phone(),), frame)
    manager._observe_mobile_phones_locked("camera-1", .5, (phone(),), frame)
    assert manager._alert_worker.jobs == []
    manager._observe_mobile_phones_locked("camera-1", 1., (phone(),), frame)
    opened = manager._alert_worker.jobs[-1]
    assert opened[0].mobile_phone_detected is True
    assert opened[1]["managed_alert_types"] == ("MOBILE_PHONE_DETECTED",)
    assert opened[1]["source_metadata"]["branch_id"] == "branch-1"
    assert opened[1]["source_metadata"]["camera_name"] == "Vault Room Camera"
    assert opened[1]["detections"][0]["bbox"] == [.05, .2, .15, .5]
    manager._access_session_contexts["session-1"]["branch_name"] = "Changed later"
    manager._observe_mobile_phones_locked("camera-1", 3., (), None)
    assert manager._alert_worker.jobs[-1][0].mobile_phone_detected is False
    manager._observe_mobile_phones_locked("camera-1", 4., (phone(),), frame)
    manager._observe_mobile_phones_locked("camera-1", 5., (phone(),), frame)
    assert manager._alert_worker.jobs[-1][0].mobile_phone_detected is True
    manager.stop()


def test_pending_phone_resets_after_gap_and_cameras_are_independent():
    manager = manager_with_capture()
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    manager.bind_camera_source("camera-2", source_type="browser_webcam", camera_name="Second Camera",
        source_context={"branch_id": "branch-2"})
    manager._observe_mobile_phones_locked("camera-1", 0., (phone(),), frame)
    manager._observe_mobile_phones_locked("camera-1", 2., (), None)
    manager._observe_mobile_phones_locked("camera-1", 3., (phone(),), frame)
    manager._observe_mobile_phones_locked("camera-2", 3., (phone(),), frame)
    manager._observe_mobile_phones_locked("camera-1", 4., (phone(),), frame)
    assert [job[1]["camera_id"] for job in manager._alert_worker.jobs] == ["camera-1"]
    manager._observe_mobile_phones_locked("camera-2", 4., (phone(),), frame)
    assert [job[1]["camera_id"] for job in manager._alert_worker.jobs] == ["camera-1", "camera-2"]
    manager.stop()


def test_rule_is_independent_and_high_severity():
    facts = evaluate(AlertSnapshot("IDLE", None, None, mobile_phone_detected=True))
    assert [(item.alert_type, item.severity) for item in facts] == [("MOBILE_PHONE_DETECTED", "HIGH")]


def test_replay_sink_exposes_phone_metadata_and_actual_evidence(tmp_path):
    sink = ReplayAlertSink(tmp_path, "replay-session")
    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    detection = {"label": "cell phone", "class_id": 77, "bbox": [.1, .2, .4, .7],
        "confidence": .82, "source_id": "replay", "detected_at": at.isoformat()}
    sink.submit(AlertSnapshot("IDLE", None, None, mobile_phone_detected=True), event_at=at,
        event_frame=np.full((40, 60, 3), 73, np.uint8), detections=(detection,),
        camera_id="replay", source_metadata={"mobile_phone_confidence": .82,
            "video_timestamp_seconds": 18.958, "branch_id": "branch-1"},
        managed_alert_types=("MOBILE_PHONE_DETECTED",))
    alert = sink.alerts[0]
    assert alert["type"] == "MOBILE_PHONE_DETECTED" and alert["severity"] == "HIGH"
    assert alert["session_id"] == "replay-session" and alert["camera_id"] == "replay"
    assert alert["video_timestamp_seconds"] == 18.958
    assert alert["metadata"]["branch_id"] == "branch-1"
    assert alert["detections"] == [detection]
    assert "82% confidence" in alert["message"]
    assert (tmp_path / f"{alert['id']}.jpg").is_file()


def test_persistence_scopes_phone_episode_away_from_existing_count_alert():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db
            db.commit()
    worker = PersistentAlertWorker(session_factory=factory)
    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    count = SnapshotJob(AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True),
        "session-1", "camera-1", at, managed_alert_types=("COUNT_MISMATCH",))
    mobile = SnapshotJob(AlertSnapshot("IDLE", None, None, mobile_phone_detected=True),
        "session-1", "phone-camera", at, source_metadata={"branch_id": "branch-1"},
        managed_alert_types=("MOBILE_PHONE_DETECTED",))
    worker._persist(count); worker._persist(mobile)
    worker._persist(SnapshotJob(AlertSnapshot("IDLE", None, None), "session-1", "phone-camera",
        at + timedelta(seconds=2), managed_alert_types=("MOBILE_PHONE_DETECTED",)))
    worker._persist(SnapshotJob(AlertSnapshot("IDLE", None, None, mobile_phone_detected=True),
        "session-1", "phone-camera", at + timedelta(seconds=3),
        source_metadata={"branch_id": "branch-1"},
        managed_alert_types=("MOBILE_PHONE_DETECTED",)))
    with Session(engine) as db:
        alerts = list(db.scalars(select(VaultRoomAlert)))
        assert [row.type for row in alerts].count("MOBILE_PHONE_DETECTED") == 2
        assert [row.type for row in alerts].count("COUNT_MISMATCH") == 1
        count_condition = db.scalar(select(VaultAlertCondition).where(
            VaultAlertCondition.alert_type == "COUNT_MISMATCH"))
        assert count_condition.active is True
        assert all(row.metadata_json.get("branch_id") == "branch-1"
            for row in alerts if row.type == "MOBILE_PHONE_DETECTED")
    engine.dispose()


def test_confirmed_phone_queues_actual_frame_and_detection_metadata(monkeypatch):
    from app.core.ml_config import load_ml_config_file
    from app.db import database
    from app.services import cloudinary_evidence, vault_alert_persistence
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db
            db.commit()
    worker = PersistentAlertWorker(session_factory=factory)
    frame = np.full((24, 32, 3), 73, np.uint8)
    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    detection = {"label": "cell phone", "class_id": 77, "bbox": [.1, .2, .4, .7],
        "confidence": .82, "source_id": "camera-1", "detected_at": at.isoformat()}
    job = SnapshotJob(AlertSnapshot("IDLE", None, None, mobile_phone_detected=True),
        "session-1", "camera-1", at, event_frame=frame, detections=(detection,),
        source_metadata={"branch_id": "branch-1", "camera_name": "Vault Room Camera"},
        managed_alert_types=("MOBILE_PHONE_DETECTED",))
    events = worker._persist(job)
    config = load_ml_config_file().model_copy(deep=True)
    config.vault_alerts.evidence.enabled = True
    config.vault_alerts.evidence.capture_mobile_phone_detected = True
    submissions = []
    monkeypatch.setattr(vault_alert_persistence, "load_ml_config_file", lambda: config)
    monkeypatch.setattr(database, "session_scope", factory)
    monkeypatch.setattr(cloudinary_evidence, "get_evidence_capture_queue",
        lambda: SimpleNamespace(submit=lambda **values: submissions.append(values)))
    worker._capture_new_alerts(events, job)
    assert len(submissions) == 1
    assert submissions[0]["captured_image"]
    assert submissions[0]["captured_at"] == at
    assert submissions[0]["camera_id"] == "camera-1"
    assert submissions[0]["metadata"]["detections"] == [detection]
    with factory() as db:
        row = db.get(VaultRoomAlert, events[0]["entity"]["id"])
        assert row.evidence_status == "PENDING"
        assert row.metadata_json["branch_id"] == "branch-1"
    engine.dispose()
