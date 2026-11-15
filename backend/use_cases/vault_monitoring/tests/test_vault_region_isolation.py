"""Isolation regressions use temporary profile storage and a temporary Grill Gate DB."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import vault_region_profiles as routes
from app.core.zones.vault_room_zone import Zone
from app.services.vault_region_monitor import VaultRegionMonitor
from app.services.vault_region_profiles import VaultRegionProfiles
from app.services.vault_room_manager import VaultRoomManager
from app.services.vault_room_replay import ReplayAlertSink, ReplaySession, VaultRoomReplayManager
from grill_gate_monitoring.services.zone_geometry import contains_point, normalized_polygon
# Reuse the existing real Grill Gate router/SQLite fixture, without changing it.
from grill_gate_monitoring.tests.test_video_job_api import harness, named_config, HEADERS


def region(left=0, right=.4):
    return dict(id='person_monitoring_roi', name='Camera-specific area', reference='bottom_center', enabled=True,
        confirmation_seconds=1, polygon=[[left, 0], [right, 0], [right, 1], [left, 1]])


def test_default_profile_root_is_stable_across_working_directories(tmp_path, monkeypatch):
    original = VaultRegionProfiles().root
    monkeypatch.chdir(tmp_path)
    assert VaultRegionProfiles().root == original
    assert original == Path(routes.__file__).resolve().parents[3] / 'var/vault-room-region-profiles'


def test_vault_and_real_grill_api_round_trips_never_modify_each_other(harness, tmp_path, monkeypatch):
    store = VaultRegionProfiles(tmp_path / 'vault-room-region-profiles')
    monkeypatch.setattr(routes, 'get_vault_region_profiles', lambda: store)
    app = FastAPI(); app.include_router(routes.router)
    client = TestClient(app, headers=HEADERS)
    base = '/api/v1/vault-room/region-profiles'
    gate_base = '/api/v1/grill-gate/zone-configurations'
    gate_payload = named_config()
    # Identical zone keys in separate use cases must still be independent.
    gate_payload['zones'][0]['zone_key'] = 'person_monitoring_roi'
    created = harness.client.post(gate_base, json=gate_payload, headers=HEADERS)
    assert created.status_code == 201, created.text
    gate_id = created.json()['id']
    gate_before = harness.client.get(f'{gate_base}/{gate_id}', headers=HEADERS).json()
    assert client.put(f'{base}/upload', json={'version': 0, 'zones': [region()]}).status_code == 200
    vault_before = client.get(f'{base}/upload').json()
    assert harness.client.get(f'{gate_base}/{gate_id}', headers=HEADERS).json() == gate_before
    changed = named_config(name='Independent Grill configuration')
    changed['zones'][0]['name'] = 'Changed gate polygon label'
    assert harness.client.put(f'{gate_base}/{gate_id}', json=changed, headers=HEADERS).status_code == 200
    assert client.get(f'{base}/upload').json() == vault_before
    named = client.post(base, json={'name': 'Second physical camera'}).json()
    assert client.put(f"{base}/{named['id']}", json={'version': named['version'], 'zones': [region(.6, 1)]}).status_code == 200
    assert client.put(f'{base}/upload', json={'version': 1, 'zones': []}).status_code == 200
    assert len(client.get(f"{base}/{named['id']}").json()['zones']) == 1
    assert VaultRegionProfiles(store.root).load(named['id'])['zones']  # Refresh/restart reload.
    assert client.get(f'{base}/webcam').json()['zones'] == []
    assert client.get(f'{base}/cctv').json()['zones'] == []
    assert client.get(f'{base}/{gate_id}').status_code == 404
    assert client.put(f'{base}/{gate_id}', json={'version': 0, 'zones': []}).status_code == 404
    foreign_zone = {**region(), 'id': 'gate_approach'}
    assert client.put(f'{base}/upload', json={'version': 2, 'zones': [foreign_zone]}).status_code == 422
    assert client.get(f'{base}/..%2Fgrill_gate').status_code in (404, 422)
    assert harness.client.get(f'{gate_base}/{gate_id}', headers=HEADERS).json()['name'] == changed['name']


def test_processing_snapshots_and_concurrent_use_case_geometry_are_independent(tmp_path):
    store = VaultRegionProfiles(tmp_path)
    original = store.save('upload', [region()], 0)
    left = VaultRegionMonitor(original)
    right_profile = {'id': 'camera-b', 'zones': [region(.6, 1)]}
    right = VaultRegionMonitor(right_profile)
    original['zones'][0]['polygon'][0][0] = .9
    right_profile['zones'].clear()
    store.save('upload', [region(.6, 1)], 1)
    person = [dict(track_id=7, x=.1, y=.1, w=.1, h=.4)]
    gate_input = dict(polygon=[[.6, 0], [1, 0], [1, 1], [.6, 1]], enabled=True)
    gate_before = deepcopy(gate_input)
    def evaluate(index):
        if index % 3 == 0:
            return left.count(person) == 1
        if index % 3 == 1:
            return right.count(person) == 0
        return not contains_point(normalized_polygon(gate_input), .15, .5)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert all(pool.map(evaluate, range(90)))
    assert gate_input == gate_before
    assert len(right.zones) == 1
    assert left.profile['zones'][0]['polygon'][0][0] == 0


def test_replay_never_inherits_live_registry_zones_and_activation_is_guarded(tmp_path):
    live = VaultRoomManager(writer=lambda _job: None)
    replay = None
    try:
        live._zone_monitor.set_zones([Zone('live_camera_only', 'Live camera', ((0, 0), (1, 0), (1, 1)))])
        live.configure_regions({'id': 'camera-a', 'zones': [region()]})
        replay = live.create_replay(clock=lambda: 1, alert_worker=ReplayAlertSink(tmp_path))
        assert replay._zone_monitor.snapshot() == []
        replay.configure_regions({'id': 'upload', 'zones': [region(.6, 1)]})
        assert live._region_monitor.profile['id'] == 'camera-a'
        assert replay._region_monitor.profile['id'] == 'upload'
        live._inference_slot.acquire()
        try:
            with pytest.raises(RuntimeError, match='frame processing'):
                live.configure_regions({'id': 'camera-b', 'zones': []})
        finally:
            live._inference_slot.release()
        live.on_access_granted('authorized-session', [], 2, True)
        with pytest.raises(RuntimeError, match='active Vault Room session'):
            live.configure_regions({'id': 'camera-b', 'zones': []})
        assert live._region_monitor.profile['id'] == 'camera-a'
    finally:
        if replay: replay.stop()
        live.stop()


def test_activation_api_returns_conflict_without_replacing_an_active_snapshot(tmp_path, monkeypatch):
    store = VaultRegionProfiles(tmp_path)
    store.save('webcam', [region()], 0)
    store.save('cctv', [region(.6, 1)], 0)
    manager = VaultRoomManager(writer=lambda _job: None)
    manager.configure_regions(store.load('webcam'))
    manager.on_access_granted('authorized-session', [], 2, True)
    monkeypatch.setattr(routes, 'get_vault_region_profiles', lambda: store)
    monkeypatch.setattr(routes, 'get_vault_room_manager', lambda: manager)
    monkeypatch.setattr(routes, 'get_vault_room_camera_manager', lambda: type('Camera', (), {'is_active': lambda _self: False})())
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[routes.require_vault_room_key] = lambda: None
    try:
        response = TestClient(app).post('/api/v1/vault-room/region-profiles/cctv/activate')
        assert response.status_code == 409
        assert manager._region_monitor.profile['id'] == 'webcam'
        assert store.load('cctv')['zones'][0]['polygon'][0][0] == .6
    finally:
        manager.stop()


def test_replay_captures_profile_before_thread_handoff(tmp_path, monkeypatch):
    manager = VaultRoomReplayManager(root=tmp_path)
    profile = {'id': 'upload', 'zones': [region()]}
    admitted, proceed = threading.Event(), threading.Event()
    captured = []
    def run(session, required, snapshot, simulated):
        admitted.set(); proceed.wait(3); captured.append(snapshot)
    monkeypatch.setattr(manager, '_run', run)
    session = ReplaySession('test-session', 'test.avi', tmp_path, tmp_path / 'test.avi', {})
    manager._sessions[session.session_id] = session
    try:
        manager.start(session.session_id, profile=profile)
        assert admitted.wait(2)
        profile['zones'].clear(); proceed.set(); session.thread.join(3)
        assert len(captured[0]['zones']) == 1
    finally:
        proceed.set(); manager.shutdown()
