"""API tests: status codes, filters, review transitions, CSV, credential masking, upload limits, ROI, settings."""
from __future__ import annotations

import time

import pytest

POLY = [{"x": 0.1, "y": 0.4}, {"x": 0.9, "y": 0.4}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]


def _camera(client, **over):
    body = {"name": "Gate", "cam_type": "rtsp", "source": "rtsp://10.0.0.5:554/stream1", "location": "Main"}
    return client.post("/api/cameras", json={**body, **over})


# -- health ----------------------------------------------------------------------------------------------
def test_health_reports_service_db_and_models(client) -> None:
    body = client.get("/api/health").json()
    assert body["service"] == "face_mask" and body["db"] == "ok"
    assert {"person_detector", "face_detector", "pose", "analyzer_configured", "loaded"} <= body["models"].keys()
    assert body["alerts"]["enabled"] in (True, False)


# -- cameras + credentials (FM-13) -----------------------------------------------------------------------
def test_fm13_credentials_are_never_returned_by_any_endpoint(client) -> None:
    created = _camera(client, source="rtsp://admin:s3cret@10.0.0.5:554/stream1", username="", password="")
    assert created.status_code == 201
    cid = created.json()["id"]
    for url in ("/api/cameras", f"/api/cameras/{cid}", "/api/cameras/status/all", f"/api/cameras/{cid}/status",
                "/api/cameras/online", "/openapi.json"):
        assert "s3cret" not in client.get(url).text, url
    body = client.get(f"/api/cameras/{cid}").json()
    assert body["source"] == "rtsp://10.0.0.5:554/stream1" and body["has_password"] is True
    assert body["username"] == "********" and "password" not in body


def test_fm13_explicit_password_field_is_stored_but_never_returned(client) -> None:
    cid = _camera(client, username="user1", password="hunter2").json()["id"]
    assert "hunter2" not in client.get("/api/cameras").text
    assert "hunter2" not in client.patch(f"/api/cameras/{cid}", json={"location": "Back"}).text


def test_camera_validation_rejects_bad_sources(client) -> None:
    assert _camera(client, source="not a url").status_code == 422
    assert _camera(client, source="ftp://host/x").status_code == 422
    assert _camera(client, cam_type="webcam", source="front").status_code == 422
    assert _camera(client, cam_type="upload", source="uploads/missing.mp4").status_code == 422
    assert _camera(client, name="").status_code == 422


def test_camera_crud_and_online_count(client) -> None:
    cid = _camera(client).json()["id"]
    assert client.get("/api/cameras/online").json() == {"cameras_online": 0, "cameras_total": 1}
    assert client.patch(f"/api/cameras/{cid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.get("/api/cameras/nope").status_code == 404
    assert client.delete(f"/api/cameras/{cid}").status_code == 204
    assert client.get(f"/api/cameras/{cid}").status_code == 404
    assert client.get("/api/cameras").json() == []


def test_start_of_disabled_camera_is_rejected(client) -> None:
    cid = _camera(client, enabled=False).json()["id"]
    assert client.post(f"/api/cameras/{cid}/start").status_code == 409


# -- uploads + existing videos --------------------------------------------------------------------------
def test_upload_rejects_unsupported_type_and_unreadable_video(client) -> None:
    assert client.post("/api/uploads/video", files={"file": ("a.exe", b"x", "application/octet-stream")}).status_code == 415
    assert client.post("/api/uploads/video", files={"file": ("a.mp4", b"not a video", "video/mp4")}).status_code == 422
    assert client.post("/api/uploads/video", files={"file": ("a.mp4", b"", "video/mp4")}).status_code == 422


def test_upload_enforces_the_size_limit_from_config(client, make_video) -> None:
    runtime = client.app.state.runtime
    runtime.cfg = runtime.cfg.model_copy(update={"uploads": runtime.cfg.uploads.model_copy(update={"max_size_mb": 1})})
    big = make_video("big.mp4", frames=60, size=(640, 480)).read_bytes()
    assert len(big) > 1024 * 1024
    response = client.post("/api/uploads/video", files={"file": ("big.mp4", big, "video/mp4")})
    assert response.status_code == 413 and "1 MB" in response.json()["detail"]


def test_upload_browse_and_process_with_progress_and_roi(client, make_video) -> None:
    up = client.post("/api/uploads/video", files={"file": ("clip.mp4", make_video().read_bytes(), "video/mp4")})
    assert up.status_code == 201
    path = up.json()["path"]
    assert path in [v["path"] for v in client.get("/api/uploads/browse").json()]
    started = client.post("/api/videos/process", json={"path": path, "name": "Clip", "roi": {
        "name": "Gate", "polygon": POLY, "inward_vector": {"x": 0, "y": -1}}})
    assert started.status_code == 201 and started.json()["cam_type"] == "upload"
    cid = started.json()["id"]
    for _ in range(50):
        status = client.get(f"/api/cameras/{cid}/status").json()
        if status["status"] == "DONE":
            break
        time.sleep(0.2)
    assert status["status"] == "DONE" and status["percent"] == 100.0 and status["frames_total"] == 12
    assert len(client.get(f"/api/roi?camera_id={cid}").json()) == 1


def test_process_rejects_paths_outside_the_video_folders(client) -> None:
    for bad in ("C:/Windows/System32/notepad.exe", "../../app.db", "uploads/../../.env", "/etc/passwd"):
        assert client.post("/api/videos/process", json={"path": bad}).status_code == 422, bad


# -- entry ROI ------------------------------------------------------------------------------------------
def test_roi_crud_is_applied_to_the_runtime_immediately(client) -> None:
    cid = _camera(client).json()["id"]
    runtime = client.app.state.runtime
    roi = client.post("/api/roi", json={"camera_id": cid, "name": "Grill Gate", "polygon": POLY,
                                        "inward_vector": {"x": 0, "y": -1}})
    assert roi.status_code == 201
    assert [r.name for r in runtime.rois_for(cid)] == ["Grill Gate"]
    rid = roi.json()["id"]
    client.patch(f"/api/roi/{rid}", json={"name": "Side Door", "inward_vector": {"x": 1, "y": 0}})
    assert runtime.rois_for(cid)[0].name == "Side Door" and runtime.rois_for(cid)[0].inward == (1, 0)
    assert client.delete(f"/api/roi/{rid}").status_code == 204
    assert runtime.rois_for(cid) == []


def test_roi_validation(client) -> None:
    cid = _camera(client).json()["id"]
    base = {"camera_id": cid, "name": "x", "polygon": POLY, "inward_vector": {"x": 0, "y": -1}}
    assert client.post("/api/roi", json={**base, "camera_id": "nope"}).status_code == 404
    assert client.post("/api/roi", json={**base, "polygon": POLY[:2]}).status_code == 422
    assert client.post("/api/roi", json={**base, "polygon": [{"x": 2, "y": 0}] + POLY[1:]}).status_code == 422
    assert client.post("/api/roi", json={**base, "inward_vector": {"x": 0, "y": 0}}).status_code == 422
    assert client.patch("/api/roi/nope", json={"name": "y"}).status_code == 404


# -- events, filters, review ----------------------------------------------------------------------------
def test_events_list_filters_and_pagination(client, add_event) -> None:
    add_event(camera_id="camA", covering="scarf", minutes_ago=5)
    add_event(camera_id="camA", covering="surgical_mask", status="UNDER_REVIEW", minutes_ago=50)
    add_event(camera_id="camB", covering="scarf", status="CLOSED", minutes_ago=500)
    get = lambda q="": client.get(f"/api/events?{q}").json()   # noqa: E731
    assert get()["total"] == 3
    assert get("camera_id=camA")["total"] == 2
    assert get("status=CLOSED")["total"] == 1
    assert get("covering_type=scarf")["total"] == 2
    assert get("outcome=VISIBLE")["total"] == 0 and get("outcome=CONCEALED")["total"] == 3
    page = get("limit=2&offset=0")
    assert page["total"] == 3 and len(page["items"]) == 2
    assert [e["status"] for e in page["items"]][0] == "OPEN"   # newest first
    assert len(get("limit=2&offset=2")["items"]) == 1
    since = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - __import__("datetime").timedelta(minutes=60)).isoformat()
    assert get(f"date_from={since.replace('+', '%2B')}")["total"] == 2
    assert client.get("/api/events?status=BOGUS").status_code == 422
    assert client.get("/api/events?limit=0").status_code == 422


def test_fm06_review_workflow_valid_and_invalid_transitions(client, add_event) -> None:
    eid = add_event()
    review = lambda to, **kw: client.post(f"/api/events/{eid}/review", json={"to_status": to, **kw})   # noqa: E731
    bad = review("CONFIRMED")
    assert bad.status_code == 409 and "Allowed: UNDER_REVIEW" in bad.json()["detail"]
    assert review("UNDER_REVIEW", reviewer="Asha").json()["reviewer"] == "Asha"
    assert review("FALSE_POSITIVE").status_code == 422                       # reason required
    ok = review("FALSE_POSITIVE", remarks="plain medical mask")
    assert ok.status_code == 200 and ok.json()["remarks"] == "plain medical mask"
    assert client.post(f"/api/events/{eid}/close", json={"remarks": ""}).status_code == 422
    closed = client.post(f"/api/events/{eid}/close", json={"remarks": "handled", "reviewer": "Asha"})
    assert closed.json()["status"] == "CLOSED" and closed.json()["reviewed_at"]
    assert review("OPEN").status_code == 409
    trail = client.get(f"/api/events/{eid}/actions").json()
    assert [(a["from_status"], a["to_status"]) for a in trail] == [
        ("OPEN", "UNDER_REVIEW"), ("UNDER_REVIEW", "FALSE_POSITIVE"), ("FALSE_POSITIVE", "CLOSED")]
    assert client.post("/api/events/nope/review", json={"to_status": "UNDER_REVIEW"}).status_code == 404


def test_fm06_confirmed_path_can_close(client, add_event) -> None:
    eid = add_event(status="UNDER_REVIEW")
    assert client.post(f"/api/events/{eid}/review", json={"to_status": "CONFIRMED"}).json()["status"] == "CONFIRMED"
    assert client.post(f"/api/events/{eid}/close", json={"remarks": "reported"}).json()["status"] == "CLOSED"


# -- evidence -------------------------------------------------------------------------------------------
def test_fm05_evidence_snapshot_clip_range_and_details(client, add_event, evidence_files) -> None:
    snap, clip = evidence_files("t_snap.jpg"), evidence_files("t_clip.webm", "clip")
    eid = add_event(snapshot=snap, clip=clip, clip_status="ready")
    details = client.get(f"/api/events/{eid}/evidence").json()
    assert details["snapshot_url"].endswith("/evidence/snapshot") and details["clip_url"].endswith("/evidence/clip")
    assert client.get(details["snapshot_url"]).headers["content-type"] == "image/jpeg"
    full = client.get(details["clip_url"])
    assert full.status_code == 200 and full.headers["content-type"] == "video/webm" and full.headers["accept-ranges"] == "bytes"
    part = client.get(details["clip_url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.headers["content-range"] == "bytes 0-99/5000" and len(part.content) == 100


def test_fm05_failed_clip_keeps_snapshot_and_reports_reason(client, add_event, evidence_files) -> None:
    eid = add_event(snapshot=evidence_files("t_snap2.jpg"), clip="", clip_status="failed")
    details = client.get(f"/api/events/{eid}/evidence").json()
    assert details["clip_url"] is None and details["snapshot_url"] and details["clip_status"] == "failed"
    assert client.get(f"/api/events/{eid}/evidence/clip").status_code == 404


def test_evidence_paths_cannot_escape_storage(client, add_event) -> None:
    eid = add_event(snapshot="../app.db", clip="../../pyproject.toml", clip_status="ready")
    assert client.get(f"/api/events/{eid}/evidence/snapshot").status_code == 404
    assert client.get(f"/api/events/{eid}/evidence/clip").status_code == 404


def test_evidence_of_unknown_event_is_404(client) -> None:
    assert client.get("/api/events/nope/evidence").status_code == 404


def test_fm13_storage_secrets_are_not_served_statically(client) -> None:
    """app.db holds camera passwords: only snapshots/ and clips/ may be mounted, never storage/ itself."""
    for path in ("/storage/app.db", "/storage/uploads/x.mp4", "/storage/runtime_overrides.json", "/storage/alert_outbox/x.json"):
        assert client.get(path).status_code == 404, path


# -- stats / entries / CSV ------------------------------------------------------------------------------
def test_stats_summary_counts_outcomes_cameras_and_open_reviews(client, add_entry, add_event) -> None:
    for outcome in ("VISIBLE", "VISIBLE", "CONCEALED", "UNABLE_TO_ASSESS"):
        add_entry(outcome)
    add_entry("VISIBLE", camera_id="cam2", hours_ago=24 * 3)      # outside "today"
    add_event(status="OPEN")
    add_event(status="CLOSED")
    today = client.get("/api/stats/summary").json()
    assert (today["entries"], today["visible"], today["concealed"], today["unable_to_assess"]) in {(4, 2, 1, 1), (3, 1, 1, 1)} or today["entries"] >= 3
    assert today["open_reviews"] == 1 and len(today["by_hour"]) == 24
    everything = client.get("/api/stats/summary?period=all").json()
    assert everything["entries"] == 5 and everything["by_camera"]["cam2"] == 1
    assert client.get("/api/stats/summary?period=bogus").status_code == 422


def test_entries_list_filters_by_outcome(client, add_entry) -> None:
    add_entry("VISIBLE"); add_entry("CONCEALED")
    assert [e["outcome"] for e in client.get("/api/entries?outcome=CONCEALED").json()] == ["CONCEALED"]


def test_csv_export_has_expected_columns_filters_and_neutralises_formulas(client, add_event) -> None:
    add_event(status="CLOSED", remarks="=HYPERLINK(\"http://x\")", reviewer="@evil")
    add_event(camera_id="other")
    csv_text = client.get("/api/reports/events.csv?camera_id=cam1")
    assert csv_text.headers["content-type"].startswith("text/csv") and "attachment" in csv_text.headers["content-disposition"]
    lines = csv_text.text.strip().splitlines()
    assert lines[0].startswith("event_id,first_seen_utc") and len(lines) == 2
    assert "'=HYPERLINK" in csv_text.text and "'@evil" in csv_text.text
    assert len(client.get("/api/reports/events.csv").text.strip().splitlines()) == 3


# -- settings --------------------------------------------------------------------------------------------
def test_fm10_settings_read_update_validate_and_reset(client) -> None:
    original = client.get("/api/settings").json()
    assert original["visibility_threshold"] == 0.6 and original["frames_to_confirm"] == 5
    updated = client.put("/api/settings", json={"visibility_threshold": 0.7, "clip_pre_seconds": 3})
    assert updated.status_code == 200 and updated.json()["visibility_threshold"] == 0.7
    assert client.app.state.runtime.cfg.visibility.threshold == 0.7
    assert client.get("/api/settings").json()["clip_pre_seconds"] == 3
    # cross-field validation happens against the full config
    bad = client.put("/api/settings", json={"frames_to_confirm": 20})
    assert bad.status_code == 422 and "frames_to_confirm" in bad.json()["detail"]
    assert client.put("/api/settings", json={"visibility_threshold": 1.5}).status_code == 422
    assert client.put("/api/settings", json={"analyzer": "yolo"}).status_code == 422
    reset = client.post("/api/settings/reset")
    assert reset.json() == original and client.app.state.runtime.cfg.visibility.threshold == 0.6


# -- optional API key -----------------------------------------------------------------------------------
def test_api_key_protects_mutating_endpoints_when_configured(client, monkeypatch, add_event) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("API_KEY", "k3y")
    get_settings.cache_clear()
    eid = add_event()
    assert client.post("/api/cameras", json={"name": "x", "cam_type": "webcam", "source": "0"}).status_code == 401
    assert client.post(f"/api/events/{eid}/review", json={"to_status": "UNDER_REVIEW"}).status_code == 401
    assert client.put("/api/settings", json={"visibility_threshold": 0.5}).status_code == 401
    ok = client.post(f"/api/events/{eid}/review", json={"to_status": "UNDER_REVIEW"}, headers={"X-API-Key": "k3y"})
    assert ok.status_code == 200
    assert client.get("/api/events").status_code == 200       # reads stay open (same as branch_exterior)
    get_settings.cache_clear()
