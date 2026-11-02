"""Plain-language explanations, the Security Brief rows and the incident report built from them."""
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.event import Event
from app.services.analytics.fusion import STRONG_WEAPON_CONFIDENCE, weapon_severity
from app.services.brief_service import build_brief
from app.services.event_explainer import explain_event, get_explanation, verification_label
from app.services.incident_report import build_incident_report

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
TECHNICAL = ("track", "#1", "ratio", "bounding", "confidence", "rfdetr", "tortuosity", "displacement")


def _event(**kw) -> Event:
    base = dict(id="abcdef1234567890", camera_id="c1", camera_name="Front Door", scenario="movement", severity="medium",
                status="open", track_ids=[1], message="Unusual movement for track #1: pacing (ratio 3.5).", confidence=0.7,
                meta={}, created_at=NOW, updated_at=NOW)
    base.update(kw)
    return Event(**base)


def _assert_plain(x: dict) -> None:
    for field in ("title", "observation", "reason", "risk", "action"):
        assert x[field], field
        assert not any(t in x[field].lower() for t in TECHNICAL), (field, x[field])


def test_pacing_is_explained_without_technical_terms():
    x = explain_event(_event(meta={"reasons": ["pacing/circling in a small area (path-to-displacement ratio 3.5)"]}))
    _assert_plain(x)
    assert "back and forth" in x["observation"]
    assert "loitering" in x["risk"]


def test_repeated_zone_approach_is_not_called_pacing():
    x = explain_event(_event(zone_name="Side Gate", meta={"patterns": ["repeated_approach"], "approaches": 3}))
    assert "3 times" in x["observation"] and "Side Gate" in x["observation"]
    assert "back and forth" not in x["observation"]


def test_loitering_near_entrance_uses_dwell_time_and_does_not_assume_intent():
    x = explain_event(_event(scenario="loitering", zone_name="Main Door", meta={"dwell_seconds": 400, "threshold_seconds": 300,
                                                                               "time_band": "business_hours", "zone_type": "entrance"}))
    _assert_plain(x)
    assert x["title"] == "Possible Loitering Near Entrance"
    assert "about 7 minutes" in x["observation"]
    assert "intention" in x["risk"]


def test_low_confidence_weapon_is_not_called_a_weapon_and_asks_for_verification():
    x = explain_event(_event(scenario="anomaly", severity="medium", confidence=0.36,
                             meta={"kind": "weapon", "label": "blunt object bat/rod/hammer-like", "method": "rfdetr-coco-crop"}))
    _assert_plain(x)
    assert "may resemble a rod-like" in x["observation"]
    assert "visual verification" in x["observation"]
    assert "not strong enough" in x["caution"]
    assert x["reliability"] == "low"


def test_zone_touch_does_not_claim_unauthorised():
    x = explain_event(_event(scenario="intrusion", severity="high", zone_name="Vault Door", meta={"kind": "zone_touch"}))
    assert "no access-control record" in x["reason"]
    assert "permission" in x["action"]


def test_gathering_is_not_labelled_suspicious():
    x = explain_event(_event(scenario="gathering", severity="low", meta={"group_size": 5, "held_seconds": 200, "time_band": "business_hours"}))
    assert "5 people" in x["observation"]
    assert "normal" in x["risk"].lower()


def test_unknown_kind_and_missing_fields_fall_back_safely():
    x = explain_event({"scenario": "anomaly", "meta": {"kind": "something_new"}})
    assert "not enough" in x["observation"]
    assert "the monitored area" in x["observation"]
    y = explain_event({})  # nothing at all
    assert y["title"]


def test_every_known_kind_produces_plain_text():
    from app.services.event_explainer import _BUILDERS

    for kind in _BUILDERS:
        _assert_plain(explain_event(_event(meta={"kind": kind, "people": 3})))


def test_explanation_is_deterministic_and_stored_copy_is_reused():
    e = _event(meta={"kind": "running"})
    assert explain_event(e) == explain_event(e)
    stored = dict(explain_event(e), title="Stored title")
    assert get_explanation(_event(meta={"kind": "running", "explanation": stored}))["title"] == "Stored title"


@pytest.mark.parametrize("conf,sev", [(0.36, "medium"), (0.5, "high"), (0.69, "high"), (STRONG_WEAPON_CONFIDENCE, "critical")])
def test_weapon_severity_depends_on_confidence(conf, sev):
    assert weapon_severity(conf) == sev


def test_verification_labels():
    assert verification_label("open") == "AI Detected - Not Yet Verified"
    assert verification_label("false_positive") == "False Alarm"
    assert verification_label("closed") == "Resolved"


def test_brief_row_and_report_share_the_same_text():
    e = _event(meta={"reasons": ["pacing/circling in a small area (path-to-displacement ratio 3.5)"]})
    row = build_brief([e], 24, now=NOW)["top_incidents"][0]
    report = build_incident_report(e, [])
    assert row["observation"] and row["observation"] in report
    assert row["message"] == e.message          # raw text stays available to API consumers
    assert row["verification"] == "AI Detected - Not Yet Verified"
    assert e.message not in report.split("Technical appendix")[0]


def test_report_with_missing_data_says_not_available():
    e = _event(camera_name="", zone_name="", meta={"kind": "running"})
    report = build_incident_report(e, [])
    assert report.count("Not available") >= 4   # branch, camera, zone, snapshot, clip
    assert "No snapshot or video clip" in report
    assert "Incident overview" in report and "Conclusion" in report


def test_report_lists_related_events_and_duration():
    e = _event(updated_at=NOW + timedelta(minutes=5), meta={"kind": "running"})
    other = _event(id="zzzz", created_at=NOW + timedelta(seconds=30), meta={"kind": "fallen"}, severity="medium")
    report = build_incident_report(e, [e, other])
    assert "about 5 minutes" in report and "Person May Have Fallen" in report
