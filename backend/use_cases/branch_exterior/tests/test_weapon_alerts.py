"""Weapon and fight alert contracts; no model weights or real database needed."""
from types import SimpleNamespace

import numpy as np

from app.schemas.settings import ThresholdConfig
from app.services.analytics.fusion import apply_weapon_override, build_anomaly_signals, weapon_severity
from app.services.analytics.signals import ScenarioSignal
from app.services.annotate import draw_weapon_objects
from app.services.detection.base import Detection
from app.services.detection.weapon_detector import associate_weapons, confirmed_weapon_detections


def _person(confirmed=True):
    return SimpleNamespace(
        detection=Detection(20, 10, 120, 210, "person"),
        weapon_flag=confirmed, weapon_confidence=0.42,
        weapon_label="knife-like object", weapon_method="rfdetr-coco-crop",
        action_label="normal", action_confidence=0.0, action_method="",
        action_debug={},
    )


def test_small_knife_in_person_crop_is_associated():
    person = _person()
    knife = Detection(95, 90, 107, 101, "weapon", 0.42, "knife", "rfdetr-coco-crop")
    hits = associate_weapons([knife], {7: person})
    assert hits[7].detection is knife
    assert hits[7].label == "knife-like object"


def test_small_gun_from_custom_model_is_associated_when_available():
    gun = Detection(95, 90, 107, 101, "weapon", 0.8, "gun", "rfdetr-weapon-crop")
    hits = associate_weapons([gun], {7: _person()})
    assert hits[7].detection is gun


def test_only_current_confirmed_weapon_box_is_drawn():
    person = _person(confirmed=False)
    knife = Detection(95, 90, 107, 101, "weapon", 0.42, "knife", "rfdetr-coco-crop")
    hits = associate_weapons([knife], {7: person})
    assert confirmed_weapon_detections(hits, {7: person}) == []
    person.weapon_flag = True
    current = confirmed_weapon_detections(hits, {7: person})
    assert current == [knife]
    frame = np.zeros((240, 160, 3), dtype=np.uint8)
    draw_weapon_objects(frame, current)
    assert np.any(frame[90, 95])
    assert not np.any(frame[40, 40])
    assert confirmed_weapon_detections({}, {7: person}) == []


def test_confirmed_weapon_alert_is_critical_and_fight_is_high():
    person = _person()
    signals = build_anomaly_signals({7: person}, {}, ThresholdConfig())
    weapon = next(s for s in signals if s.meta.get("kind") == "weapon")
    assert weapon.severity_hint == "critical"
    assert weapon.track_ids == [7]
    assert weapon_severity(0.7) == "critical"
    assert not build_anomaly_signals({7: person}, {}, ThresholdConfig(), current_weapon_ids=set())

    person.weapon_flag = False
    person.action_label = "fighting"
    person.action_confidence = 0.75
    person.action_method = "pose"
    fight = build_anomaly_signals({7: person}, {}, ThresholdConfig())
    assert len(fight) == 1
    assert fight[0].meta["kind"] == "fighting"
    assert fight[0].severity_hint == "high"


def test_only_current_confirmed_weapon_overrides_other_signal():
    thresholds = ThresholdConfig()
    movement = ScenarioSignal(scenario="movement", track_ids=[7], confidence=0.7,
                              severity_hint="medium", message="Pacing")
    assert apply_weapon_override(movement, set(), thresholds).severity_hint == "medium"
    assert apply_weapon_override(movement, {7}, thresholds).severity_hint == "critical"
    assert movement.meta["override"] == "weapon_present"
