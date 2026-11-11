from grill_gate_monitoring.services.gate_classification import GateClassificationTracker


def test_classification_confirmation_fallback_and_stale_timeout():
    tracker = GateClassificationTracker(confirmation_frames=2, stale_after_seconds=3)
    assert tracker.update({"class": "closed", "confidence": .9}, 0).state == "UNKNOWN"
    update = tracker.update({"class": "closed", "confidence": .9}, 1)
    assert update.state == "CLOSED" and update.confirmed_state == "CLOSED"
    assert tracker.update(None, 2).state == "CLOSED"
    assert tracker.update({"class": "surprise", "confidence": .9}, 3).using_fallback
    assert tracker.update(None, 4.1).state == "UNKNOWN"
    assert tracker.update({"class": "partially_open", "confidence": .9}, 5).state == "UNKNOWN"
    update = tracker.update({"class": "partially_open", "confidence": .9}, 6)
    assert update.state == "PARTIALLY_OPEN" and update.direction == "OPENING"


def test_missing_or_invalid_confidence_does_not_confirm_a_class():
    tracker = GateClassificationTracker(confirmation_frames=1, stale_after_seconds=2)
    for result in ({"class": "closed"}, {"class": "closed", "confidence": "bad"},
                   {"class": "closed", "confidence": 1.1}, {"class": "unknown", "confidence": .9}):
        update = tracker.update(result, 0)
        assert not update.valid
        assert update.state == "UNKNOWN"
