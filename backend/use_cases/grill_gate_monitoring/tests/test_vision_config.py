from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.ml_config import get_vault_room_config
from app.services import grill_gate_runtime
from grill_gate_monitoring.schemas.vision import GrillGateVisionSettings
from grill_gate_monitoring.services.frame_processor import SerializedPersonDetector
from grill_gate_monitoring.services.vision_config import get_grill_gate_vision_config
from app.services import person_tracker as person_tracker_module


def test_grill_gate_vision_defaults_are_loaded_independently_of_vault_room():
    gate = get_grill_gate_vision_config()
    vault = get_vault_room_config().counting

    assert gate.detector.model == "rfdetr-nano"
    assert gate.detector.confidence == vault.detector.confidence
    assert gate.tracker.minimum_matching_threshold == vault.tracker.minimum_matching_threshold
    assert not isinstance(gate, type(vault))

    changed = gate.model_copy(update={
        "detector": gate.detector.model_copy(update={"confidence": 0.23}),
    })
    assert changed.detector.confidence == 0.23
    assert get_grill_gate_vision_config().detector.confidence == 0.5
    assert get_vault_room_config().counting.detector.confidence == vault.detector.confidence


def test_grill_gate_detector_resolution_uses_only_supported_shape_multiple():
    config = GrillGateVisionSettings.model_validate({
        "detector": {"inference_resolution": 512},
        "tracker": {},
    })
    assert config.detector.inference_resolution == 512
    with pytest.raises(ValidationError, match="multiple of 32"):
        GrillGateVisionSettings.model_validate({"detector": {"inference_resolution": 510}})
    with pytest.raises(ValidationError):
        GrillGateVisionSettings.model_validate({"detector": {"model": "rfdetr-large"}})


def test_grill_gate_tracker_passes_native_lost_track_buffer(monkeypatch):
    seen = {}

    def byte_track(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(person_tracker_module.sv, "ByteTrack", byte_track)
    person_tracker_module.PersonTracker(get_grill_gate_vision_config())
    assert seen == {
        "track_activation_threshold": 0.4,
        "lost_track_buffer": 90,
        "minimum_matching_threshold": 0.7,
        "frame_rate": 1,
        "minimum_consecutive_frames": 2,
    }


def test_grill_gate_detector_instance_uses_gate_config_and_keeps_serialization(monkeypatch):
    config = get_grill_gate_vision_config()

    class DetectorStub:
        def __init__(self, received):
            self.config = received

    monkeypatch.setattr(grill_gate_runtime, "RfDetrPersonDetector", DetectorStub)
    grill_gate_runtime._get_person_detector.cache_clear()
    try:
        wrapped = grill_gate_runtime._get_person_detector()
        assert isinstance(wrapped, SerializedPersonDetector)
        assert wrapped._detector.config is config
    finally:
        grill_gate_runtime._get_person_detector.cache_clear()


def test_live_and_uploaded_sessions_each_receive_a_new_tracker(monkeypatch):
    detector = object()
    publisher = SimpleNamespace(submit=lambda _event: True, active_conditions=lambda *_args: [])
    writer = SimpleNamespace(submit=lambda _event: True)
    monkeypatch.setattr(grill_gate_runtime, "_get_person_detector", lambda: detector)
    monkeypatch.setattr(grill_gate_runtime, "get_grill_gate_alert_publisher", lambda: publisher)
    monkeypatch.setattr(grill_gate_runtime, "get_grill_gate_event_writer", lambda: writer)
    grill_gate_runtime.get_grill_gate_video_jobs.cache_clear()
    try:
        live_a = grill_gate_runtime._frame_processor_factory("camera-a", "assignment-a")
        live_b = grill_gate_runtime._frame_processor_factory("camera-b", "assignment-b")
        jobs = grill_gate_runtime.get_grill_gate_video_jobs()
        video_a = jobs.processor_factory("video-a", None)
        video_b = jobs.processor_factory("video-b", None)
    finally:
        grill_gate_runtime.get_grill_gate_video_jobs.cache_clear()

    processors = (live_a, live_b, video_a, video_b)
    assert all(processor._detector is detector for processor in processors)
    assert all(processor._tracker._config is get_grill_gate_vision_config() for processor in processors)
    assert len({id(processor._tracker) for processor in processors}) == len(processors)
    assert len({id(processor._tracker._tracker) for processor in processors}) == len(processors)
