"""Scenarios A-J (docs/face_mask/SCENARIOS.md) with a scripted detector: deterministic, no real models.

The tracker, entry logic, quality gate, heuristic analyzer (C and I) and event state machine are the real code.
Test names carry the SCENARIO id and the FM requirement ids they prove.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.config import VisibilityConfig
from app.ml.visibility_analyzer import HeuristicVisibilityAnalyzer
from tests.integration.fakes import (
    FakePose, Person, TagAnalyzer, TAG_COVERED, TAG_PLAIN, pass_by, run_scenario, walk_in,
)

pytestmark = pytest.mark.integration

COVERED = lambda x=480, **kw: Person(walk_in(x, **kw), tag=TAG_COVERED)   # noqa: E731
PLAIN = lambda x=480, **kw: Person(walk_in(x, **kw), tag=TAG_PLAIN)       # noqa: E731


def _outcomes(sink):
    return sorted(o for _, o in sink.entries)


def test_scenarioA_fm02_normal_visible_face_logs_entry_only(cfg) -> None:
    sink = run_scenario(cfg, [PLAIN()], TagAnalyzer())
    assert sink.opened == [] and _outcomes(sink) == ["VISIBLE"]


def test_scenarioB_fm03_mask_creates_exactly_one_event(cfg) -> None:
    sink = run_scenario(cfg, [COVERED()], TagAnalyzer("surgical_mask"))
    assert len(sink.opened) == 1 and sink.opened[0].covering_type == "surgical_mask"
    assert _outcomes(sink) == ["CONCEALED"]


def test_scenarioC_fm04_head_turned_away_is_not_an_alert(cfg) -> None:
    """REAL heuristic analyzer: no face, nose/eyes not visible, only one shoulder (body not frontal) -> UNABLE."""
    turned = {"left_ear": (470.0, 300.0, 0.9), "left_shoulder": (520.0, 450.0, 0.9), "right_shoulder": (440.0, 450.0, 0.2)}
    analyzer = HeuristicVisibilityAnalyzer(cfg.visibility, None)
    sink = run_scenario(cfg, [PLAIN()], analyzer, pose=FakePose(turned))
    assert sink.opened == []
    assert "CONCEALED" not in _outcomes(sink)


def test_scenarioD_fm03_group_of_three_only_the_concealed_one_alerts(cfg) -> None:
    people = [PLAIN(200), COVERED(480), PLAIN(760)]
    sink = run_scenario(cfg, people, TagAnalyzer())
    assert len(sink.opened) == 1
    assert _outcomes(sink) == ["CONCEALED", "VISIBLE", "VISIBLE"]


def test_scenarioE_fm01_passing_by_without_entering_is_ignored(cfg) -> None:
    sink = run_scenario(cfg, [Person(pass_by(), tag=TAG_COVERED)], TagAnalyzer(), frames=45)
    assert sink.opened == [] and sink.entries == []


def test_scenarioE_fm01_walking_sideways_inside_the_roi_is_not_entering(cfg) -> None:
    sink = run_scenario(cfg, [Person(pass_by(y=600), tag=TAG_COVERED)], TagAnalyzer(), frames=40)
    assert sink.opened == [] and sink.entries == []


def test_scenarioF_fm04_poor_light_is_unable_to_assess_without_alert(cfg) -> None:
    """REAL quality gate: a dark scene never reaches the analyzer; the track ends UNABLE_TO_ASSESS."""
    sink = run_scenario(cfg, [COVERED()], TagAnalyzer(), brightness=0.12)
    assert sink.opened == [] and _outcomes(sink) == ["UNABLE_TO_ASSESS"]


def test_scenarioF_fm04_blurry_head_never_alerts(cfg) -> None:
    flat = np.full((720, 960, 3), 120, np.uint8)   # no texture at all: Laplacian variance ~ 0

    class Flat:
        def __init__(self) -> None: self.i = 0

    from tests.integration import fakes
    original = fakes.make_frame
    fakes.make_frame = lambda people, i, brightness=1.0: flat
    try:
        sink = run_scenario(cfg, [COVERED()], TagAnalyzer())
    finally:
        fakes.make_frame = original
    assert sink.opened == []


def test_scenarioG_fm03_covered_person_lingering_gives_one_event(cfg) -> None:
    sink = run_scenario(cfg, [COVERED(linger_after=25)], TagAnalyzer(), frames=200)
    assert len(sink.opened) == 1 and len(sink.updates) > 20


def test_scenarioH_fm03_scarf_even_partial_alerts(cfg) -> None:
    sink = run_scenario(cfg, [COVERED()], TagAnalyzer("scarf"))
    assert len(sink.opened) == 1 and sink.opened[0].covering_type == "scarf"


def _cap_analyzer(cfg, policy: str) -> HeuristicVisibilityAnalyzer:
    vis = VisibilityConfig(**{**cfg.visibility.model_dump(), "head_down_policy": policy})
    return HeuristicVisibilityAnalyzer(vis, None)


FRONTAL_NO_FACE = {"left_shoulder": (560.0, 450.0, 0.95), "right_shoulder": (400.0, 450.0, 0.95)}   # facing camera, head down


def test_scenarioI_fm04_cap_hiding_face_looking_down_alerts_with_default_policy(cfg) -> None:
    """REAL heuristic: frontal body (both shoulders), no face, no skin in the head crop -> head_covering."""
    gray = Person(walk_in(480), tag=128, achromatic=True)   # grey head region: Cr ~128, below the skin floor
    sink = run_scenario(cfg, [gray], _cap_analyzer(cfg, "concealed_if_frontal_body_and_no_skin"), pose=FakePose(FRONTAL_NO_FACE))
    assert len(sink.opened) == 1 and sink.opened[0].covering_type == "head_covering"


def test_scenarioI_fm04_head_down_policy_unable_never_alerts(cfg) -> None:
    gray = Person(walk_in(480), tag=128, achromatic=True)
    sink = run_scenario(cfg, [gray], _cap_analyzer(cfg, "unable"), pose=FakePose(FRONTAL_NO_FACE))
    assert sink.opened == []


def test_scenarioJ_fm02_sunglasses_only_is_visible_without_alert(cfg) -> None:
    sink = run_scenario(cfg, [PLAIN()], TagAnalyzer())     # real sunglasses handling is covered in test_visibility_rules
    assert sink.opened == [] and _outcomes(sink) == ["VISIBLE"]


def test_scenarioK_fm03_two_concealed_people_two_events(cfg) -> None:
    sink = run_scenario(cfg, [COVERED(300), COVERED(660)], TagAnalyzer())
    assert len(sink.opened) == 2


def test_fm01_no_roi_means_nobody_is_evaluated(cfg) -> None:
    sink = run_scenario(cfg, [COVERED()], TagAnalyzer(), rois=[])
    assert sink.opened == [] and sink.entries == []
