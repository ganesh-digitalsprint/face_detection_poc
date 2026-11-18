"""Coverage mapping and exact-frame evidence regressions."""
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.ml.tracker import Detection
from app.ml.types import VisibilityResult
from app.ml.visibility_analyzer import classify_coverage
from app.core.config import EvidenceConfig
from app.services.annotate import annotate
from app.services.detection_pipeline import DetectionPipeline
from app.services.event_service import EventService, NewEvent, verify_evidence_candidate
from app.services.evidence_service import EvidenceRecorder
from app.services.observation import EvidenceCandidate, TrackObservation
from app.services.runtime import RuntimeSink


def test_three_coverage_states(cfg):
    setting = cfg.visibility
    assert classify_coverage(.05, {"nose": .9, "mouth": .9, "chin": .9}, "sunglasses", setting).coverage_state == "VISIBLE"
    partial = classify_coverage(.65, {"nose": .9, "mouth": .1, "chin": .1}, "lower_face_covering", setting)
    assert (partial.state, partial.coverage_state) == ("CONCEALED", "PARTIALLY_COVERED")
    full = classify_coverage(.95, {"nose": .1, "mouth": .1, "chin": .1}, "lower_face_covering", setting)
    assert full.coverage_state == "FULLY_COVERED"


def test_low_resolution_head_never_calls_analyzer_or_alerts(cfg):
    class SmallPersonDetector:
        def detect(self, frame):
            return [Detection((30, 20, 80, 120), .9)]

    class Analyzer:
        name = "fake"

        def analyze(self, crop, keypoints):
            raise AssertionError("a 30 px head must not be classified")

    pipeline = DetectionPipeline(cfg, "cam", SmallPersonDetector(), None, Analyzer())
    frame = np.full((240, 320, 3), 110, np.uint8)
    pipeline.process_frame(frame, 0, [])
    result = pipeline.process_frame(frame, .2, [])
    assert len(result.observations) == 1
    assert result.observations[0].display == "LOW_RES"
    assert result.observations[0].visibility is None
    assert not result.observations[0].evidence_candidates


def test_quality_failure_keeps_previous_exact_frame_evidence(cfg):
    """A later unassessable frame must not pair its box with an older image."""
    from app.services.detection_pipeline import _TrackMemory

    pipeline = DetectionPipeline(cfg, "cam", object(), None, object())
    earlier = np.full((480, 640, 3), 120, dtype=np.uint8)
    candidate = EvidenceCandidate(earlier, (120, 70, 260, 420), (140, 75, 220, 150),
                                  7, 1.2, 100, "CONCEALED")
    pipeline._memory[3] = _TrackMemory(candidates=[candidate], verified_candidate=candidate)
    current = np.zeros((480, 640, 3), dtype=np.uint8)
    obs = pipeline._observe(current, 2.0, 3, (450, 60, 580, 430), (640, 480), [], True)
    assert not obs.quality_passed
    assert obs.evidence_candidates[0] is candidate
    assert obs.box != obs.evidence_candidates[0].person_box


def test_unassessed_overlay_is_dashed_not_a_concealment_box():
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    obs = TrackObservation(ts=0, camera_id="cam", track_id=1, box=(10, 10, 60, 70),
                           foot=(35, 70), in_roi=False, entering=False, display="LOW_RES")
    result = annotate(frame, [obs], [])
    assert result[70, 16].any()  # dash on the lower edge, clear of the label
    assert not result[70, 24].any()  # gap between lower-edge dashes
    assert result[70, 16, 0] > result[70, 16, 2]  # grey-blue, not orange/red


def _event(candidates):
    return NewEvent(camera_id="cam", roi_id=None, roi_name="", track_id=3, ts=1.0,
                    score=.8, covering_type="mask", frames_evaluated=5, head_box=(0, 0, 10, 10),
                    best_frame=candidates[0].frame, best_crop=None, person_box=candidates[0].person_box,
                    candidates=tuple(candidates))


def test_verifier_retries_exact_frame_and_box():
    class Detector:
        def detect(self, frame):
            # Fake moving person: detection comes from the image, never from track state.
            x = int(frame[0, 0, 0])
            return [Detection((x, 10, x + 20, 50), .9)]

    wrong = EvidenceCandidate(np.full((64, 96, 3), 10, np.uint8), (50, 10, 70, 50),
                              (54, 12, 62, 24), 10, .5, 90, "CONCEALED")
    right = EvidenceCandidate(np.full((64, 96, 3), 30, np.uint8), (30, 10, 50, 50),
                              (34, 12, 42, 24), 11, .6, 80, "CONCEALED")
    selected = verify_evidence_candidate(_event([wrong, right]), Detector(), .5)
    assert selected.verified and selected.frame_id == 11
    assert selected.snapshot_video_ts == .6 and selected.person_box == right.person_box
    assert selected.ts == 1.0  # clip timing stays at confirmation, not the earlier snapshot
    rejected = verify_evidence_candidate(_event([wrong]), Detector(), .5)
    assert not rejected.verified and rejected.verification_iou == 0


@dataclass
class Sink:
    opened: list = field(default_factory=list)
    upgrades: list = field(default_factory=list)

    def log_entry(self, *args):
        pass

    def open_event(self, event):
        self.opened.append(event)
        return "event-one"

    def update_event(self, *args):
        pass

    def upgrade_event(self, *args):
        self.upgrades.append(args)


def test_partial_to_full_upgrades_one_event(cfg):
    sink = Sink()
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    partial = VisibilityResult(.65, "CONCEALED", "mask_below_nose", {}, "PARTIALLY_COVERED")
    full = VisibilityResult(.95, "CONCEALED", "surgical_mask", {}, "FULLY_COVERED")
    for i in range(cfg.confirmation.frames_to_confirm + 2):
        service.process(TrackObservation(ts=i * .2, camera_id="cam", track_id=3,
                                        box=(10, 10, 30, 50), foot=(20, 50), in_roi=True,
                                        entering=True, visibility=partial))
    assert len(sink.opened) == 1 and sink.opened[0].coverage_state == "PARTIALLY_COVERED"
    service.process(TrackObservation(ts=5, camera_id="cam", track_id=3,
                                    box=(10, 10, 30, 50), foot=(20, 50), in_roi=True,
                                    entering=True, visibility=full))
    assert len(sink.opened) == 1
    assert len(sink.upgrades) == 1
    assert sink.upgrades[0][:4] == ("event-one", "FULLY_COVERED", .95, "surgical_mask")
    assert sink.upgrades[0][4].track_id == 3


def test_full_upgrade_keeps_original_snapshot_and_selects_verified_new_frame(tmp_path, monkeypatch):
    from app.services import evidence_service, runtime as runtime_module

    class Detector:
        def detect(self, frame):
            x = int(frame[0, 0, 0])
            return [Detection((x, 10, x + 20, 50), .9)]

    row = SimpleNamespace(coverage_state="PARTIALLY_COVERED", snapshot_path="")

    class Repository:
        def __init__(self, _session):
            pass

        async def get(self, _event_id):
            return row

        async def update_fields(self, _event_id, **fields):
            for key, value in fields.items():
                setattr(row, key, value)

    class Writer:
        def __init__(self):
            self.jobs = []

        def submit(self, job):
            self.jobs.append(job)

    monkeypatch.setattr(runtime_module, "EventRepository", Repository)
    monkeypatch.setattr(evidence_service, "relative_to_storage", lambda path: str(path))
    recorder = EvidenceRecorder(EvidenceConfig(clip_pre_seconds=1, clip_post_seconds=2, snapshot_quality=85),
                                snapshot_dir=tmp_path / "screenshots", clip_dir=tmp_path / "clips")
    writer = Writer()
    runtime = SimpleNamespace(writer=writer, evidence=recorder,
                              cfg=SimpleNamespace(evidence=SimpleNamespace(min_box_iou=.5)),
                              models=lambda: SimpleNamespace(person=Detector()),
                              evidence_submit=lambda fn, *args: fn(*args))
    sink = RuntimeSink(runtime)
    partial_frame = np.full((64, 96, 3), 10, np.uint8)
    partial = NewEvent(camera_id="cam", roi_id=None, roi_name="", track_id=3, ts=.5,
                       score=.65, covering_type="mask_below_nose", frames_evaluated=3,
                       head_box=(14, 12, 22, 24), best_frame=partial_frame, best_crop=None,
                       person_box=(10, 10, 30, 50), coverage_state="PARTIALLY_COVERED", frame_id=5)
    sink._store_snapshot("event-one", partial, datetime.now(timezone.utc))
    original_path = tmp_path / "screenshots" / "event-one.jpg"
    original_bytes = original_path.read_bytes()

    full_frame = np.full((64, 96, 3), 30, np.uint8)
    candidate = EvidenceCandidate(full_frame, (30, 10, 50, 50), (34, 12, 42, 24),
                                  10, 1.0, 90, "CONCEALED", "FULLY_COVERED")
    observation = TrackObservation(ts=1.0, camera_id="cam", track_id=3, box=candidate.person_box,
                                   foot=(40, 50), in_roi=True, entering=True,
                                   evidence_candidates=(candidate,))
    sink.upgrade_event("event-one", "FULLY_COVERED", .95, "surgical_mask", observation)
    assert len(writer.jobs) == 3
    # Even if the earlier partial snapshot's DB job arrives last, it cannot
    # replace the newer full-coverage path.
    for index in (1, 2, 0):
        asyncio.run(writer.jobs[index](None))
    assert row.coverage_state == "FULLY_COVERED"
    assert Path(row.snapshot_path).is_file() and Path(row.snapshot_path) != original_path
    assert original_path.read_bytes() == original_bytes
    details = json.loads(Path(row.snapshot_path).with_suffix(".json").read_text(encoding="utf-8"))
    assert details["verification"] == "verified" and details["frame_id"] == 10
    recorder.shutdown()


def test_pending_partial_clip_adopts_full_color_without_rewriting_a_finished_clip(tmp_path):
    recorder = EvidenceRecorder(EvidenceConfig(clip_pre_seconds=1, clip_post_seconds=2, snapshot_quality=85),
                                snapshot_dir=tmp_path / "screenshots", clip_dir=tmp_path / "clips")
    recorder.start_clip("cam", "event-one", 1.0, lambda *_args: None, 3, "PARTIALLY_COVERED")
    assert recorder._pending["cam"][0].coverage_state == "PARTIALLY_COVERED"
    recorder.upgrade_pending_clip("event-one", "FULLY_COVERED")
    assert recorder._pending["cam"][0].coverage_state == "FULLY_COVERED"
    recorder.shutdown()
