"""Settings page fields added for the common Settings UI: FPS, detection confidence, entering movement, alert channels."""
from __future__ import annotations


def test_extended_settings_round_trip_and_reset(client) -> None:
    original = client.get("/api/settings").json()
    for key in ("processing_fps", "person_confidence", "entering_window_frames", "entering_min_displacement_px",
                "alert_dashboard", "alert_sms", "alert_email", "alert_app"):
        assert key in original
    updated = client.put("/api/settings", json={
        "processing_fps": 4, "person_confidence": 0.5, "entering_window_frames": 8,
        "entering_min_displacement_px": 20, "alert_sms": True})
    assert updated.status_code == 200
    body = updated.json()
    assert body["processing_fps"] == 4 and body["alert_sms"] is True and body["person_confidence"] == 0.5
    cfg = client.app.state.runtime.cfg
    assert cfg.stream.processing_fps == 4 and cfg.alerts.channels.sms is True and cfg.entering.window_frames == 8
    assert client.get("/api/settings").json()["entering_min_displacement_px"] == 20
    assert client.post("/api/settings/reset").json() == original


def test_extended_settings_are_validated(client) -> None:
    assert client.put("/api/settings", json={"processing_fps": 0}).status_code == 422
    assert client.put("/api/settings", json={"person_confidence": 2}).status_code == 422
    assert client.put("/api/settings", json={"entering_window_frames": 1}).status_code == 422
    assert client.put("/api/settings", json={"alert_sms": "maybe"}).status_code == 422
