from __future__ import annotations

from dataclasses import dataclass, field

from app.ml.types import VisibilityResult
from app.services.event_service import EventService, NewEvent, TrackState
from app.services.observation import TrackObservation

CONCEALED = VisibilityResult(0.9, "CONCEALED", "lower_face_covering")
VISIBLE = VisibilityResult(0.1, "VISIBLE")
UNABLE = VisibilityResult(0.0, "UNABLE")


@dataclass
class FakeSink:
    entries: list = field(default_factory=list)
    opened: list = field(default_factory=list)
    updates: list = field(default_factory=list)

    def log_entry(self, camera_id, roi_id, track_id, outcome, score, frames_evaluated, ts) -> None:
        self.entries.append((camera_id, track_id, outcome))

    def open_event(self, event: NewEvent) -> str:
        self.opened.append(event)
        return f"evt{len(self.opened)}"

    def update_event(self, event_id, ts, frames_evaluated, best_score, covering_type) -> None:
        self.updates.append((event_id, frames_evaluated))


def _obs(track: int, ts: float, vis=None, *, entering=True, in_roi=True, cam="cam1", foot=(500.0, 700.0)):
    return TrackObservation(ts=ts, camera_id=cam, track_id=track, box=(0, 0, 10, 10), foot=foot, in_roi=in_roi,
                            entering=entering, roi_id="r1", roi_name="Gate", visibility=vis,
                            quality_passed=None if vis is None else True)


def _service(cfg):
    sink = FakeSink()
    return EventService(cfg.confirmation, cfg.cooldown, sink), sink


def test_fm03_concealed_person_creates_exactly_one_event(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(cfg.confirmation.frames_to_confirm + 10):
        svc.process(_obs(1, i * 0.2, CONCEALED))
    assert len(sink.opened) == 1
    assert svc.state_of("cam1", 1) == TrackState.CONCEALMENT_EVENT_OPEN
    assert sink.entries == [("cam1", 1, "CONCEALED")]
    assert len(sink.updates) >= 10          # later frames update the same event, never a second one


def test_fm03_single_concealed_frame_is_not_enough(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(cfg.confirmation.frames_to_confirm - 1):
        svc.process(_obs(1, i * 0.2, CONCEALED))
    assert sink.opened == []
    assert svc.state_of("cam1", 1) == TrackState.EVALUATING


def test_fm03_isolated_concealed_frames_among_visible_do_not_alert(cfg) -> None:
    svc, sink = _service(cfg)
    pattern = [VISIBLE, CONCEALED, VISIBLE, VISIBLE, CONCEALED, VISIBLE, VISIBLE, VISIBLE, VISIBLE, VISIBLE]
    for i, vis in enumerate(pattern):
        svc.process(_obs(1, i * 0.2, vis))
    assert sink.opened == []
    assert sink.entries == [("cam1", 1, "VISIBLE")]
    assert svc.state_of("cam1", 1) == TrackState.CLEARED


def test_fm02_visible_person_only_writes_entry_log(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(cfg.confirmation.frames_to_confirm + 3):
        svc.process(_obs(1, i * 0.2, VISIBLE))
    assert sink.opened == [] and sink.updates == []
    assert sink.entries == [("cam1", 1, "VISIBLE")]


def test_fm03_two_concealed_people_create_two_events(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(cfg.confirmation.frames_to_confirm + 2):
        svc.process(_obs(1, i * 0.2, CONCEALED, foot=(500.0, 700.0)))
        svc.process(_obs(2, i * 0.2, CONCEALED, foot=(540.0, 705.0)))   # right next to the first, same time
    assert len(sink.opened) == 2
    assert {e.track_id for e in sink.opened} == {1, 2}


def test_fm03_lingering_concealed_person_still_one_event(cfg) -> None:
    svc, sink = _service(cfg)
    svc.process(_obs(1, 0.0, None, entering=True))        # walks in: evaluation starts
    for i in range(1, 300):                               # then a minute of standing at the door; the movement
        svc.process(_obs(1, i * 0.2, CONCEALED, entering=False))   # test no longer says "entering"
    assert len(sink.opened) == 1
    assert svc.state_of("cam1", 1) == TrackState.CONCEALMENT_EVENT_OPEN


def test_fm04_unable_frames_never_alert_or_clear(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(30):
        svc.process(_obs(1, i * 0.2, UNABLE))
    assert sink.opened == [] and sink.entries == []
    assert svc.state_of("cam1", 1) == TrackState.EVALUATING


def test_fm04_track_ending_while_evaluating_is_unable_to_assess_without_alert(cfg) -> None:
    svc, sink = _service(cfg)
    svc.process(_obs(1, 0.0, UNABLE))
    assert svc.end_track("cam1", 1, 1.0) == TrackState.UNABLE_TO_ASSESS
    assert sink.opened == []
    assert sink.entries == [("cam1", 1, "UNABLE_TO_ASSESS")]


def test_fm01_person_passing_by_is_never_evaluated(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(20):
        svc.process(_obs(1, i * 0.2, None, entering=False, in_roi=False))
    svc.end_track("cam1", 1, 5.0)
    assert sink.opened == [] and sink.entries == []


def test_fm01_waiting_in_roi_then_entering_is_evaluated_later(cfg) -> None:
    svc, sink = _service(cfg)
    for i in range(10):
        svc.process(_obs(1, i * 0.2, None, entering=False))
    assert svc.state_of("cam1", 1) == TrackState.IN_ENTRY_ROI
    for i in range(cfg.confirmation.frames_to_confirm):
        svc.process(_obs(1, 3 + i * 0.2, CONCEALED, entering=True))
    assert len(sink.opened) == 1


def test_fm03_fragmented_track_in_same_place_merges_into_existing_event(cfg) -> None:
    svc, sink = _service(cfg)
    n = cfg.confirmation.frames_to_confirm
    for i in range(n):
        svc.process(_obs(1, i * 0.2, CONCEALED))
    svc.end_track("cam1", 1, 2.0)                          # tracker lost the person...
    for i in range(n):
        svc.process(_obs(2, 3.0 + i * 0.2, CONCEALED, foot=(510.0, 705.0)))   # ...and re-found them as track 2
    assert len(sink.opened) == 1
    assert ("evt1", n) in sink.updates


def test_fm03_cooldown_expires_so_a_later_visit_is_a_new_event(cfg) -> None:
    svc, sink = _service(cfg)
    n = cfg.confirmation.frames_to_confirm
    for i in range(n):
        svc.process(_obs(1, i * 0.2, CONCEALED))
    svc.end_track("cam1", 1, 2.0)
    later = 2.0 + cfg.cooldown.seconds + 5
    for i in range(n):
        svc.process(_obs(2, later + i * 0.2, CONCEALED))
    assert len(sink.opened) == 2


def test_fm03_cooldown_is_per_camera(cfg) -> None:
    svc, sink = _service(cfg)
    n = cfg.confirmation.frames_to_confirm
    for i in range(n):
        svc.process(_obs(1, i * 0.2, CONCEALED, cam="camA"))
    svc.end_track("camA", 1, 2.0)
    for i in range(n):
        svc.process(_obs(1, 3.0 + i * 0.2, CONCEALED, cam="camB"))
    assert len(sink.opened) == 2


def test_fm03_cooldown_different_place_is_a_new_event(cfg) -> None:
    svc, sink = _service(cfg)
    n = cfg.confirmation.frames_to_confirm
    for i in range(n):
        svc.process(_obs(1, i * 0.2, CONCEALED, foot=(100.0, 700.0)))
    svc.end_track("cam1", 1, 2.0)
    for i in range(n):
        svc.process(_obs(2, 3.0 + i * 0.2, CONCEALED, foot=(900.0, 700.0)))
    assert len(sink.opened) == 2
