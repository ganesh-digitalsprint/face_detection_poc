import copy

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import vault_region_profiles as routes
from app.core.ml_config import get_vault_room_config
from app.services.person_detector import Detection
from app.services.vault_region_monitor import VaultRegionMonitor
from app.services.vault_region_profiles import REGIONS, VaultRegionProfiles
from app.services.vault_room_manager import VaultRoomManager
from app.services.vault_room_replay import ReplayAlertSink


def zone(key, *, seconds=1, polygon=None):
    return dict(id=key, name=REGIONS[key], reference="bottom_center", confirmation_seconds=seconds,
        polygon=polygon or [[0, 0], [.75, 0], [.75, 1], [0, 1]])


def track(identifier, x=.1):
    return dict(track_id=identifier, x=x, y=.1, w=.1, h=.5)


def test_entry_confirmation_is_roi_scoped_once_per_session_and_has_no_exit_events():
    monitor = VaultRegionMonitor(dict(zones=[zone(key) for key in REGIONS]))
    tracks = [track(1), track(2, .3), track(3, .85)]
    assert monitor.count(tracks) == 2
    assert monitor.update(0, tracks, None) == []
    events = monitor.update(1, tracks, 2)
    assert [event[0] for event in events].count("PERSON_ENTERED") == 1
    assert [event[0] for event in events].count("VAULT_AREA_ENTERED") == 2
    assert monitor.update(2, tracks, 2) == []
    assert monitor.update(3, [], 0) == []  # Re-arm without implementing exit detection.
    assert monitor.update(4, tracks, 2) == []
    events = monitor.update(5, tracks, 2)
    assert {event[0] for event in events} == {"PERSON_DETECTED", "VAULT_AREA_ENTERED"}
    monitor.reset()
    monitor.update(6, tracks, 2)
    assert "PERSON_ENTERED" in [event[0] for event in monitor.update(7, tracks, 2)]


def test_flicker_track_changes_and_missing_frames_do_not_confirm_an_entry():
    monitor = VaultRegionMonitor(dict(zones=[zone("person_monitoring_roi"), zone("vault_area_roi")]))
    monitor.update(0, [track(1), track(2)], 2)
    assert monitor.update(.9, [track(1), track(3)], 2) == []
    assert not any(item[0] == "PERSON_ENTERED" for item in monitor.update(1, [track(1), track(3)], 2))
    assert monitor.update(10, [track(1), track(3)], 2) == []
    assert "PERSON_ENTERED" in [item[0] for item in monitor.update(11, [track(1), track(3)], 2)]
    config_only = VaultRegionMonitor(dict(zones=[zone("vault_door_roi"), zone("tray_area_roi"), zone("ornament_area_roi")]))
    config_only.update(0, [track(1)], 1)
    assert config_only.update(30, [track(1)], 1) == []


def test_profiles_persist_version_and_keep_source_profiles_and_global_zones_separate(tmp_path):
    store = VaultRegionProfiles(tmp_path / "vault")
    assert {item["id"] for item in store.list()} == {"webcam", "cctv", "upload"}
    saved = store.save("upload", [zone(key) for key in REGIONS], 0)
    assert saved["version"] == 1
    assert len(VaultRegionProfiles(tmp_path / "vault").load("upload")["zones"]) == len(REGIONS)
    assert store.load("webcam")["zones"] == []
    with pytest.raises(RuntimeError):
        store.save("upload", [], 0)
    with pytest.raises(ValueError):
        store.save("../grill_gate", [], 0)
    with pytest.raises(ValueError):
        store.save("upload", [zone("tray_area_roi"), zone("tray_area_roi")], 1)
    invalid = zone("vault_area_roi"); invalid["polygon"][0][0] = 2
    with pytest.raises(ValueError):
        store.save("upload", [invalid], 1)
    assert store.load("upload") == saved
    new = store.create("Camera at the vault door")
    assert new["id"] not in {"webcam", "cctv", "upload"}
    store.save("upload", [], 1)
    assert store.load(new["id"])["zones"] == []


def test_zone_set_name_saves_with_unchanged_polygons_and_version_validation(profile_client):
    client, root = profile_client
    rows = [zone(key) for key in REGIONS]
    response = client.put(f"{BASE}/upload", json={"version": 0, "zones": rows, "name": "Vault Night Shift – Gate A"})
    assert response.status_code == 200
    saved = response.json()
    assert saved['name'] == 'Vault Night Shift – Gate A'
    assert saved['zones'] == VaultRegionProfiles(root).load('upload')['zones']
    assert [row['polygon'] for row in saved['zones']] == [row['polygon'] for row in rows]
    assert client.put(f"{BASE}/upload", json={"version": 0, "zones": rows, "name": "Stale"}).status_code == 409
    assert client.put(f"{BASE}/upload", json={"version": 1, "zones": rows, "name": "   "}).status_code == 422
    assert client.get(f"{BASE}/upload").json() == saved


def test_profile_api_auth_validation_version_conflict_and_camera_admission(tmp_path, monkeypatch):
    store = VaultRegionProfiles(tmp_path)
    monkeypatch.setattr(routes, "get_vault_region_profiles", lambda: store)
    monkeypatch.setattr(routes.require_vault_room_key.__globals__["settings"], "VAULT_ROOM_API_KEY", "secret")
    app = FastAPI(); app.include_router(routes.router)
    client = TestClient(app)
    base = "/api/v1/vault-room/region-profiles"
    assert client.get(base).status_code == 401
    client.headers["X-API-Key"] = "secret"
    assert client.get(base).status_code == 200
    assert client.put(base + "/upload", json={"version": 0, "zones": [zone("vault_area_roi")]}).status_code == 200
    assert client.put(base + "/upload", json={"version": 0, "zones": []}).status_code == 409
    invalid = zone("vault_area_roi", seconds=-1)
    assert client.put(base + "/upload", json={"version": 1, "zones": [invalid]}).status_code == 422
    monkeypatch.setattr(routes, "get_vault_room_camera_manager", lambda: type("Camera", (), {"is_active": lambda _self: True})())
    assert client.post(base + "/upload/activate").status_code == 409


def test_real_room_tracker_and_counter_use_roi_and_replay_does_not_modify_live_manager(tmp_path):
    class Detector:
        status = {"status": "ready"}
        def detect(self, _frame):
            return [Detection(10, 10, 25, 60, .99), Detection(35, 10, 50, 60, .99), Detection(85, 10, 99, 60, .99)]
    cfg = get_vault_room_config()
    cfg = cfg.model_copy(update={"counting": cfg.counting.model_copy(update={"count_stable_seconds": .3,
        "stable_min_samples": 2, "tracker": cfg.counting.tracker.model_copy(update={"minimum_consecutive_frames": 1})})})
    live = VaultRoomManager(config=cfg, detector=Detector(), writer=lambda _job: None)
    now = [1.0]
    worker = live.create_replay(clock=lambda: now[0], alert_worker=ReplayAlertSink(tmp_path))
    before = copy.deepcopy(live.state())
    try:
        profile = dict(id="upload", zones=[zone("person_monitoring_roi", seconds=.2), zone("vault_area_roi", seconds=.2)])
        worker.configure_regions(profile)
        worker.on_access_granted("test-replay", [], 2, True)
        for index in range(12):
            now[0] = 1 + index / 10
            result = worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source="replay")
        assert len(result["tracks"]) == 3
        assert result["raw_count"] == 2
        assert result["stable_count"] == 2
        events = list(worker._events)
        assert [item["type"] for item in events].count("PERSON_ENTERED") == 1
        assert [item["type"] for item in events].count("VAULT_AREA_ENTERED") == 2
        assert live.state() == before
    finally:
        worker.stop(); live.stop()


@pytest.fixture
def profile_client(tmp_path, monkeypatch):
    store = VaultRegionProfiles(tmp_path / "profiles")
    monkeypatch.setattr(routes, "get_vault_region_profiles", lambda: store)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.require_vault_room_key] = lambda: None
    return TestClient(app), store.root


BASE = "/api/v1/vault-room/region-profiles"


def test_all_five_regions_round_trip_edit_delete_restart_and_profile_isolation(profile_client):
    client, root = profile_client
    rows = [dict(zone(key, seconds=.35, polygon=[[.123456789123, .1], [.85, .1], [.85, .95], [.123456789123, .95]]),
                 name=f"Region {index}", enabled=index != 2, reference="center")
            for index, key in enumerate(REGIONS)]
    for identifier in ("upload", "webcam", "cctv"):
        assert client.get(f"{BASE}/{identifier}").status_code == 200
    response = client.put(f"{BASE}/upload", json={"version": 0, "zones": rows})
    assert response.status_code == 200, response.text
    saved = response.json()
    for before, after in zip(rows, saved["zones"]):
        assert after["polygon"] == before["polygon"]
        for key in ("name", "reference", "confirmation_seconds"):
            assert after[key] == before[key]
        assert after.get("enabled", True) == before["enabled"]
    assert client.get(f"{BASE}/upload").json() == saved
    assert VaultRegionProfiles(root).load("upload") == saved  # New store after service restart.
    custom = client.post(BASE, json={"name": "Second recording viewpoint"})
    assert custom.status_code == 201
    custom = custom.json()
    assert custom["id"] not in ("upload", "webcam", "cctv")
    assert client.put(f"{BASE}/{custom['id']}", json={"version": custom["version"], "zones": rows}).status_code == 200
    edited = copy.deepcopy(rows)
    edited[0]["polygon"][0][0] = .15
    assert client.put(f"{BASE}/upload", json={"version": saved["version"], "zones": edited}).status_code == 200
    assert client.put(f"{BASE}/upload", json={"version": 2, "zones": edited[:-1]}).status_code == 200
    assert client.get(f"{BASE}/upload").json()["zones"][0]["polygon"] == edited[0]["polygon"]
    assert len(VaultRegionProfiles(root).load("upload")["zones"]) == len(REGIONS)-1
    assert client.get(f"{BASE}/{custom['id']}").json()["zones"][0]["polygon"] == rows[0]["polygon"]
    assert client.get(f"{BASE}/webcam").json()["zones"] == []
    assert client.get(f"{BASE}/cctv").json()["zones"] == []
    assert client.put(f"{BASE}/missing", json={"version": 0, "zones": rows}).json()["detail"] == "Vault Room region profile not found"


@pytest.mark.parametrize("field,value", [
    ("id", "gate_approach"), ("name", "x" * 61), ("reference", "feet"), ("enabled", "yes"),
    ("confirmation_seconds", -1), ("confirmation_seconds", 61),
    ("polygon", [[0, 0], [.5, .5]]),
    ("polygon", [[-.0000000001, 0], [1, 0], [1, 1]]),
    ("polygon", [[0, 0], [1.0000000001, 0], [1, 1]]),
    ("polygon", [[True, 0], [1, 0], [1, 1]]),
    ("polygon", [["0", 0], [1, 0], [1, 1]]),
    ("polygon", [[0, 0, 1], [1, 0], [1, 1]]),
])
def test_profile_payload_rejects_invalid_fields_with_details(profile_client, field, value):
    client, _root = profile_client
    row = dict(zone("vault_area_roi"), **{field: value})
    response = client.put(f"{BASE}/upload", json={"version": 0, "zones": [row]})
    assert response.status_code == 422
    assert any(field in error["loc"] for error in response.json()["detail"])
    assert client.get(f"{BASE}/upload").json()["zones"] == []


def test_main_application_registers_existing_profile_router():
    from app.main import create_app
    schema = create_app().openapi()["paths"]
    assert {"get", "post"} <= schema[BASE].keys()
    assert {"get", "put"} <= schema[f"{BASE}/{{profile_id}}"].keys()
