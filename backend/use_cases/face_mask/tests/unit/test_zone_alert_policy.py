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
