from app.services.detection_pipeline import DetectionPipeline
from tests.integration.fakes import FakePose, Person, ScriptedDetector, TagAnalyzer, make_frame


def test_covered_display_latches_then_releases_after_sustained_visible_evidence(cfg):
    person = Person(lambda _: (500, 700), tag=200)
    pipeline = DetectionPipeline(cfg, "cam", ScriptedDetector([person]), FakePose(), TagAnalyzer())
    states = []
    for frame_number in range(24):
        if frame_number == 9:
            person.tag = 100
        rows = pipeline.process_frame(make_frame([person], frame_number), frame_number * 0.2, []).observations
        if rows:
            states.append(rows[0].display)
    assert "CONCEALED" in states[:9]
    assert "CONCEALED" in states[9:15]  # not released on the first visible frame
    assert states[-1] == "VISIBLE"
