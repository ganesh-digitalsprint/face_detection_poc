import os
import sqlite3

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.routes.platform import validate_host, validate_rtsp_url
from app.api.routes import platform
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(tmp_path / "platform.db"))
    monkeypatch.setenv("FEDBANK_PLATFORM_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("FEDBANK_PLATFORM_FERNET_KEY", Fernet.generate_key().decode())
    return TestClient(app)


def write(client, path, payload):
    return client.post(f"/api/platform{path}", json=payload, headers={"X-Platform-Admin-Key": "test-admin-key"})


def test_local_demo_creates_hierarchy_but_not_cameras_or_uploads(client, monkeypatch):
    monkeypatch.delenv("FEDBANK_PLATFORM_ADMIN_KEY")
    assert client.post("/api/platform/zones", json={"name": "South"}).status_code == 503
    monkeypatch.setenv("FEDBANK_PLATFORM_DEMO_WRITES", "1")
    local = TestClient(app, base_url="http://127.0.0.1:8011", client=("127.0.0.1", 50800))
    zone_response = local.post("/api/platform/zones", json={"name": "South"})
    assert zone_response.status_code == 201, zone_response.text
    city_response = local.post("/api/platform/cities", json={"zone_id": zone_response.json()["id"], "name": "Bengaluru"})
    assert city_response.status_code == 201, city_response.text
    branch_response = local.post("/api/platform/branches", json={"city_id": city_response.json()["id"], "code": "C99127-01", "name": "Main"})
    assert branch_response.status_code == 201, branch_response.text
    assert local.post("/api/platform/cameras/bulk", json={"recorder": {"branch_id": branch_response.json()["id"], "host": "127.0.0.1"}, "cameras": [{"channel_no": 1, "name": "Door", "use_case": "face_mask"}]}).status_code == 503
    assert local.post("/api/platform/uploads", json={"branch_id": branch_response.json()["id"], "name": "test.mp4", "size": 100}).status_code == 503
    remote = TestClient(app, base_url="http://127.0.0.1:8011", client=("192.168.1.3", 50801))
    assert remote.post("/api/platform/zones", json={"name": "Remote"}).status_code == 503


def test_hierarchy_and_atomic_cameras(client):
    assert client.post("/api/platform/zones", json={"name": "South"}).status_code == 403
    zone = write(client, "/zones", {"name": "South"}).json()
    assert write(client, "/zones", {"name": "South"}).status_code == 409
    assert write(client, "/cities", {"zone_id": "missing", "name": "Bengaluru"}).status_code == 404
    city = write(client, "/cities", {"zone_id": zone["id"], "name": "Bengaluru"}).json()
    assert write(client, "/branches", {"city_id": city["id"], "code": "C99127-01", "name": "Main", "pincode": "560001"}).status_code == 201
    assert write(client, "/branches", {"city_id": city["id"], "code": "C99127-01", "name": "Duplicate"}).status_code == 409
    branch = client.get("/api/platform/branches", params={"city_id": city["id"]}).json()["items"][0]
    assert branch["camera_count"] == 0
    assert client.get("/api/platform/zones").json()[0]["branch_count"] == 1
    payload = {"recorder": {"branch_id": branch["id"], "host": "192.168.10.65", "username": "admin", "password": "private-test-password"},
               "cameras": [{"channel_no": 1, "name": "Door", "use_case": "face_mask"},
                           {"channel_no": 2, "name": "Lobby", "use_case": "branch_exterior"}]}
    result = write(client, "/cameras/bulk", payload)
    assert result.status_code == 201, result.text
    assert len(result.json()["cameras"]) == 2
    assert result.json()["recorder"]["has_password"] is True
    assert "private-test-password" not in result.text
    assert "private-test-password" not in client.get(f"/api/platform/branches/{branch['id']}/recorders").text
    assert client.get(f"/api/platform/branches/{branch['id']}/cameras").json()[0]["use_cases"] == "face_mask"
    assert write(client, "/cameras/bulk", payload).status_code == 409
    assert len(client.get(f"/api/platform/branches/{branch['id']}/recorders").json()) == 1
    with sqlite3.connect(os.environ["FEDBANK_PLATFORM_DB_PATH"]) as conn:
        assert "private-test-password" not in conn.execute("SELECT password_encrypted FROM recorders").fetchone()[0]


@pytest.mark.parametrize("host", ["169.254.169.254", "224.0.0.1", "8.8.8.8", "metadata.google.internal", "10.0.0.1/../../secret"])
def test_disallowed_hosts(host):
    with pytest.raises(ValueError):
        validate_host(host)


@pytest.mark.parametrize("url", ["file:///tmp/a", "http://127.0.0.1/video", "concat:rtsp://10.0.0.1/x", "rtsp://169.254.169.254/x"])
def test_disallowed_schemes_and_urls(url):
    with pytest.raises(ValueError):
        validate_rtsp_url(url)


def test_private_rtsp_is_allowed():
    assert validate_rtsp_url("rtsp://admin:secret@192.168.1.2:554/live")[:4] == ("rtsp", "192.168.1.2", 554, "/live")


def test_rtsps_query_is_preserved_in_probe(client, monkeypatch):
    seen = []
    monkeypatch.setattr(platform, "probe_url", lambda url, timeout: seen.append(url) or {"ok": True, "width": 1280, "height": 720, "fps": 25, "codec": "H264"})
    response = write(client, "/recorders/test", {"branch_id": "unused", "mode": "single", "full_url": "rtsps://admin:secret@10.0.0.8:8554/live?profile=main"})
    assert response.status_code == 200, response.text
    assert seen == ["rtsps://admin:secret@10.0.0.8:8554/live?profile=main"]
    assert "secret" not in response.text


def test_channel_discovery_stops_after_consecutive_failures(client, monkeypatch):
    attempted = []

    def fake_probe(url, _timeout):
        attempted.append(url)
        return {"ok": len(attempted) <= 2, "width": 1280, "height": 720, "fps": 25, "codec": "unknown"}

    monkeypatch.setattr(platform, "probe_url", fake_probe)
    response = write(client, "/recorders/test?max_channels=32", {"branch_id": "unused", "host": "10.0.0.8", "password": "private-test-password"})
    assert response.status_code == 200, response.text
    assert response.json()["channel_count"] == 2
    assert len(attempted) == 5
    assert "private-test-password" not in response.text


def test_probe_rejects_public_host_before_opening(client, monkeypatch):
    monkeypatch.setattr(platform, "probe_url", lambda *_: pytest.fail("Probe should not run"))
    response = write(client, "/recorders/test", {"branch_id": "unused", "host": "169.254.169.254"})
    assert response.status_code == 422


def test_existing_recorder_table_gets_additive_scheme_column(client, monkeypatch, tmp_path):
    path = os.environ["FEDBANK_PLATFORM_DB_PATH"]
    monkeypatch.setattr(platform, "repo_root", lambda: tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE recorders (id TEXT PRIMARY KEY, branch_id TEXT, mode TEXT, host TEXT, rtsp_port INTEGER, username TEXT, password_encrypted TEXT, path_template TEXT, stream INTEGER, transport TEXT)")
        conn.execute("CREATE TABLE video_uploads (id TEXT PRIMARY KEY)")
    assert client.get("/api/platform/health").status_code == 200
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(recorders)")}
        assert "scheme" in columns
    assert client.get("/api/platform/health").status_code == 200
