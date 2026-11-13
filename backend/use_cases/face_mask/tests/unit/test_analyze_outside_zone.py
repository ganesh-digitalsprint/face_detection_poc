"""A saved entry zone must never suppress face visibility analysis."""
from app.services.detection_pipeline import DetectionPipeline
from app.services.entry_service import RoiSpec
from tests.integration.fakes import FakePose, Person, ScriptedDetector, TagAnalyzer, make_frame


def test_covered_person_outside_zone_is_analysed_and_plotted(cfg):
    person = Person(lambda _: (150, 690), tag=200)
    distant_zone = RoiSpec("door", "Door", ((0.7, 0.4), (0.95, 0.4), (0.95, 0.95), (0.7, 0.95)), (0, -1))
    pipeline = DetectionPipeline(cfg, "cam", ScriptedDetector([person]), FakePose(), TagAnalyzer())
    observations = []
    for frame_number in range(12):
        observations += pipeline.process_frame(make_frame([person], frame_number), frame_number * 0.2,
                                               [distant_zone]).observations
    assert observations
    assert all(not observation.in_roi for observation in observations)
    assert any(observation.visibility and observation.visibility.state == "CONCEALED" for observation in observations)
    assert any(observation.display == "CONCEALED" for observation in observations)
    assert all(observation.display != "NOT_ENTERING" for observation in observations)
