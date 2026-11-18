from app.ml.types import VisibilityResult
from app.services.event_service import EventService
from app.services.observation import TrackObservation
from tests.integration.fakes import RecordingSink


def observation(track, frame, inside, entering=False):
    return TrackObservation(ts=frame / 5, camera_id="cam", track_id=track,
                            box=(100 * track, 100, 100 * track + 70, 350),
                            foot=(100 * track + 35, 350), in_roi=inside, entering=entering,
                            roi_id="zone" if inside else None, roi_name="Door" if inside else "",
                            visibility=VisibilityResult(0.9, "CONCEALED", "mask"), display="CONCEALED")


def test_covered_person_outside_zone_is_not_an_alert_then_entry_alerts_once(cfg):
    sink = RecordingSink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    for frame in range(10):
        service.process(observation(1, frame, False))
    assert sink.opened == []
    for frame in range(10, 20):
        service.process(observation(1, frame, True))
    assert len(sink.opened) == 1
    assert sink.opened[0].track_id == 1


def test_two_people_entering_together_get_separate_events(cfg):
    sink = RecordingSink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    for frame in range(10):
        for track in (1, 2):
            service.process(observation(track, frame, frame >= 6))
    assert [event.track_id for event in sink.opened] == [1, 2]
    assert sink.opened[0].person_box != sink.opened[1].person_box


def test_soft_direction_does_not_block_covered_zone_entry(cfg):
    sink = RecordingSink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    for frame in range(7):
        service.process(observation(1, frame, True, entering=False))
    assert len(sink.opened) == 1


def test_strict_direction_requires_inward_motion(cfg):
    sink = RecordingSink()
    analysis = cfg.analysis.model_copy(update={"direction_mode": "strict"})
    service = EventService(cfg.confirmation, cfg.cooldown, sink, analysis)
    for frame in range(7):
        service.process(observation(1, frame, True, entering=False))
    assert sink.opened == []
    service.process(observation(1, 8, True, entering=True))
    assert len(sink.opened) == 1


def test_cached_overlay_frames_do_not_count_as_five_independent_assessments(cfg):
    sink = RecordingSink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    service.process(observation(1, 0, True))
    from dataclasses import replace
    for frame in range(1, 10):
        service.process(replace(observation(1, frame, True), visibility_fresh=False))
    assert sink.opened == []
    for frame in range(10, 14):
        service.process(observation(1, frame, True))
    assert len(sink.opened) == 1


def test_unverified_saved_roi_box_cannot_open_an_alert(cfg):
    from dataclasses import replace
    sink = RecordingSink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    for frame in range(10):
        service.process(replace(observation(1, frame, True), zone_verified=False))
    assert sink.opened == []
    service.process(replace(observation(1, 11, True), zone_verified=True))
    assert len(sink.opened) == 1


def test_saved_roi_verification_is_not_latched_across_frames(cfg, monkeypatch):
    """A real person on one frame cannot validate a later false box on the doorway."""
    from collections import deque
    import numpy as np
    from app.services.detection_pipeline import DetectionPipeline, _TrackMemory
    from app.services.entry_service import RoiSpec

    pipeline = DetectionPipeline(cfg, "cam", object(), None, object())
    pipeline._memory[1] = _TrackMemory(window=deque(
        [VisibilityResult(.9, "CONCEALED", "mask")] * cfg.confirmation.frames_to_confirm,
        maxlen=cfg.confirmation.confirm_window))
    checks = iter((True, False))
    monkeypatch.setattr(pipeline, "_verify_box", lambda frame, box: next(checks))
    roi = RoiSpec("door", "Door", ((0, 0), (1, 0), (1, 1), (0, 1)), (0, -1))
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    first = pipeline._observe(frame, 1.0, 1, (100, 80, 250, 400), (640, 480), [roi], False)
    second = pipeline._observe(frame, 1.2, 1, (100, 80, 250, 400), (640, 480), [roi], False)
    assert first.zone_verified is True
    assert second.zone_verified is False


def test_saved_roi_rejects_a_verified_person_from_outside_the_zone(cfg):
    from dataclasses import replace
    import numpy as np
    from app.services.observation import EvidenceCandidate

    sink = RecordingSink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    outside = EvidenceCandidate(frame, (1, 1, 10, 20), (2, 2, 5, 7), 1, .2, 10,
                                "CONCEALED", in_roi=False, verified=True)
    for index in range(8):
        service.process(replace(observation(1, index, True), frame_id=index + 1,
                                evidence_candidates=(outside,)))
    assert sink.opened == []
    inside = replace(outside, frame_id=9, in_roi=True)
    service.process(replace(observation(1, 9, True), frame_id=9,
                            evidence_candidates=(outside, inside)))
    assert len(sink.opened) == 1
    assert sink.opened[0].candidates == (inside,)


def test_video_can_opt_out_of_saved_roi_without_changing_the_saved_zone():
    from app.services.entry_service import RoiSpec
    from app.services.runtime import Runtime

    runtime = object.__new__(Runtime)
    saved = RoiSpec("door", "Door", ((.3, .3), (.5, .3), (.5, .8)), (0, -1))
    runtime._rois = {"cam": [saved]}
    runtime._ignore_saved_rois = set()
    assert runtime.effective_rois_for("cam") == [saved]
    runtime.set_use_saved_roi("cam", False)
    assert runtime.effective_rois_for("cam")[0].id == "__default_full_frame__"
    assert runtime.rois_for("cam") == [saved]
    runtime.set_use_saved_roi("cam", True)
    assert runtime.effective_rois_for("cam") == [saved]
