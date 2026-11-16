import os
import sqlite3
import json

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


def test_branch_full_edit_move_concurrency_and_audit(client):
    zone = write(client, "/zones", {"name": "South"}).json()
    other_zone = write(client, "/zones", {"name": "North"}).json()
    city = write(client, "/cities", {"zone_id": zone["id"], "name": "Old City"}).json()
    other_city = write(client, "/cities", {"zone_id": other_zone["id"], "name": "New City"}).json()
    branch = write(client, "/branches", {"city_id": city["id"], "name": "Main", "code": "MAIN-01"}).json()
    competing = write(client, "/branches", {"city_id": other_city["id"], "name": "Taken", "code": "TAKEN-01"}).json()
    with sqlite3.connect(os.environ["FEDBANK_PLATFORM_DB_PATH"]) as conn:
        conn.execute("INSERT INTO video_uploads(id,branch_id,original_name,stored_path,size) VALUES(?,?,?,?,?)",
                     ("test-upload", branch["id"], "sample.mp4", "uploads/MAIN-01/2026-11/test-upload_sample.mp4", 100))
    url = f"/api/platform/branches/{branch['id']}"
    headers = {"X-Platform-Admin-Key": "test-admin-key"}
    assert client.patch(url, json={"updated_at": branch["updated_at"], "name": "Wrong"}).status_code == 403
    assert client.get("/api/platform/branches/code-available", params={"code": "TAKEN-01"}).json() == {"available": False}
    invalid = [
        {"name": " "}, {"code": "!bad"}, {"status": "retired"}, {"pincode": "123"},
        {"phone": "abc"}, {"email": "bad"}, {"timezone": "Not/AZone"},
        {"city_id": other_city["id"], "zone_id": zone["id"]},
    ]
    for change in invalid:
        assert client.patch(url, json={"updated_at": branch["updated_at"], **change}, headers=headers).status_code == 422
    for change in [{"code": competing["code"]}, {"city_id": other_city["id"], "name": "Taken"}]:
        assert client.patch(url, json={"updated_at": branch["updated_at"], **change}, headers=headers).status_code == 409
    changed = client.patch(url, json={"updated_at": branch["updated_at"], "city_id": other_city["id"],
        "zone_id": other_zone["id"], "code": "MAIN-02", "name": "Main New", "status": "inactive",
        "address": "12 Road", "pincode": "560001", "timezone": "UTC", "manager": "Manager",
        "phone": "+919876543210", "email": "manager@example.com"}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["id"] == branch["id"] and changed.json()["code"] == "MAIN-02"
    assert client.patch(url, json={"updated_at": branch["updated_at"], "name": "Stale"}, headers=headers).status_code == 409
    counts = {item["name"]: item["branch_count"] for item in client.get("/api/platform/zones").json()}
    assert counts == {"South": 0, "North": 2}
    assert client.get("/api/platform/branches", params={"city_id": city["id"]}).json()["total"] == 0
    assert client.get("/api/platform/branches", params={"city_id": other_city["id"]}).json()["total"] == 2
    with sqlite3.connect(os.environ["FEDBANK_PLATFORM_DB_PATH"]) as conn:
        audit = json.loads(conn.execute("SELECT changes_json FROM branch_change_log WHERE branch_id=?", (branch["id"],)).fetchone()[0])
        assert audit["code"] == {"old": "MAIN-01", "new": "MAIN-02"}
        assert audit["city_id"]["new"] == other_city["id"]
        assert audit["zone_id"] == {"old": zone["id"], "new": other_zone["id"]}
        assert conn.execute("SELECT stored_path FROM video_uploads WHERE id='test-upload'").fetchone()[0] == "uploads/MAIN-01/2026-11/test-upload_sample.mp4"


def test_zone_and_city_quick_rename_remain_available(client):
    headers = {"X-Platform-Admin-Key": "test-admin-key"}
    zone = write(client, "/zones", {"name": "South"}).json()
    other = write(client, "/zones", {"name": "North"}).json()
    city = write(client, "/cities", {"zone_id": zone["id"], "name": "Bengaluru"}).json()
    duplicate = write(client, "/cities", {"zone_id": zone["id"], "name": "Mysuru"}).json()
    assert client.patch(f"/api/platform/zones/{zone['id']}", json={"name": "New"}).status_code == 403
    assert client.patch(f"/api/platform/zones/{zone['id']}", json={"name": other["name"]}, headers=headers).status_code == 409
    assert client.patch(f"/api/platform/zones/{zone['id']}", json={"name": "South West"}, headers=headers).json()["name"] == "South West"
    assert client.patch(f"/api/platform/cities/{city['id']}", json={"name": duplicate["name"]}, headers=headers).status_code == 409
    assert client.patch(f"/api/platform/cities/{city['id']}", json={"name": "Bangalore"}, headers=headers).json()["name"] == "Bangalore"


@pytest.mark.parametrize("field,value", [
    ("name", "New Main"), ("code", "NEW-01"), ("status", "inactive"),
    ("address", "42 Main Road"), ("pincode", "560001"), ("timezone", "UTC"),
    ("manager", "New Manager"), ("phone", "+919876543210"), ("email", "new@example.com"),
])
def test_branch_partial_update_field(client, field, value):
    zone = write(client, "/zones", {"name": "South"}).json()
    city = write(client, "/cities", {"zone_id": zone["id"], "name": "Bengaluru"}).json()
    branch = write(client, "/branches", {"city_id": city["id"], "name": "Main", "code": "MAIN-01"}).json()
    result = client.patch(f"/api/platform/branches/{branch['id']}",
                          json={"updated_at": branch["updated_at"], field: value},
                          headers={"X-Platform-Admin-Key": "test-admin-key"})
    assert result.status_code == 200, result.text
    assert result.json()[field] == value
    assert result.json()["id"] == branch["id"]


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


def test_local_vite_token_allows_only_hierarchy_writes(client, monkeypatch, tmp_path):
    monkeypatch.delenv("FEDBANK_PLATFORM_ADMIN_KEY")
    monkeypatch.delenv("FEDBANK_PLATFORM_DEMO_WRITES", raising=False)
    key_path = tmp_path / "local-demo.key"
    key_path.write_text("local-test-token", encoding="ascii")
    monkeypatch.setattr(platform, "LOCAL_DEMO_KEY_PATH", key_path)
    local = TestClient(app, base_url="http://127.0.0.1:8011", client=("127.0.0.1", 50800))
    headers = {"X-Platform-Admin-Key": "local-test-token"}
    assert local.post("/api/platform/zones", json={"name": "Unauthenticated"}).status_code == 503
    assert local.post("/api/platform/zones", json={"name": "Wrong token"}, headers={"X-Platform-Admin-Key": "wrong"}).status_code == 503
    created = local.post("/api/platform/zones", json={"name": "East"}, headers=headers)
    assert created.status_code == 201, created.text
    city = local.post("/api/platform/cities", json={"zone_id": created.json()["id"], "name": "Bengaluru"}, headers=headers)
    assert city.status_code == 201, city.text
    branch = local.post("/api/platform/branches", json={"city_id": city.json()["id"], "name": "Main", "code": "C99127-01"}, headers=headers)
    assert branch.status_code == 201, branch.text
    camera = {"recorder": {"branch_id": branch.json()["id"], "host": "127.0.0.1"}, "cameras": [{"channel_no": 1, "name": "Door", "use_case": "face_mask"}]}
    assert local.post("/api/platform/cameras/bulk", json=camera, headers=headers).status_code == 503
    upload = {"branch_id": branch.json()["id"], "name": "test.mp4", "size": 100}
    assert local.post("/api/platform/uploads", json=upload, headers=headers).status_code == 503
    remote = TestClient(app, base_url="http://127.0.0.1:8011", client=("192.168.1.3", 50801))
    assert remote.post("/api/platform/zones", json={"name": "Remote"}, headers=headers).status_code == 503


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
