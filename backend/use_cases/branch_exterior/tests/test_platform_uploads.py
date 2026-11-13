import os
import shutil
import subprocess

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.routes import platform_uploads
from app.main import app

HEADERS = {"X-Platform-Admin-Key": "test-admin-key"}


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(tmp_path / "platform.db"))
    monkeypatch.setenv("FEDBANK_PLATFORM_ADMIN_KEY", HEADERS["X-Platform-Admin-Key"])
    monkeypatch.setenv("FEDBANK_PLATFORM_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("FEDBANK_STORAGE_ROOT", str(tmp_path / "media"))
    (tmp_path / "media").mkdir()
    client = TestClient(app)
    zone = client.post("/api/platform/zones", json={"name": "Default"}, headers=HEADERS).json()
    city = client.post("/api/platform/cities", json={"name": "Default", "zone_id": zone["id"]}, headers=HEADERS).json()
    branch = client.post("/api/platform/branches", json={"name": "Default branch", "city_id": city["id"], "code": "DEFAULT-01"}, headers=HEADERS).json()
    return client, branch, tmp_path


def test_resume_offset_and_cancel(prepared):
    client, branch, tmp_path = prepared
    response = client.post("/api/platform/uploads", json={"branch_id": branch["id"], "name": "..\\video.mp4", "size": 6}, headers=HEADERS)
    assert response.status_code == 201, response.text
    ident = response.json()["id"]
    assert client.patch(f"/api/platform/uploads/{ident}", content=b"abc", headers={**HEADERS, "Upload-Offset": "1"}).status_code == 409
    assert client.patch(f"/api/platform/uploads/{ident}", content=b"abc", headers={**HEADERS, "Upload-Offset": "0"}).json()["offset"] == 3
    assert client.get(f"/api/platform/uploads/{ident}").json()["received"] == 3
    assert client.patch(f"/api/platform/uploads/{ident}", content=b"def", headers={**HEADERS, "Upload-Offset": "3"}).json()["offset"] == 6
    assert client.delete(f"/api/platform/uploads/{ident}", headers=HEADERS).status_code == 200
    assert client.get(f"/api/platform/uploads/{ident}").status_code == 404
    assert not list((tmp_path / "media" / "temp").rglob("*.part"))


def test_rejects_extension_size_and_wrong_branch(prepared):
    client, branch, _ = prepared
    base = {"branch_id": branch["id"], "name": "ok.mp4", "size": 3}
    assert client.post("/api/platform/uploads", json={**base, "name": "bad.txt"}, headers=HEADERS).status_code == 415
    assert client.post("/api/platform/uploads", json={**base, "size": 2 * 1024 ** 3 + 1}, headers=HEADERS).status_code == 413
    assert client.post("/api/platform/uploads", json={**base, "branch_id": "missing"}, headers=HEADERS).status_code == 404


def test_completed_upload_is_playable_and_listed(prepared, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are unavailable")
    client, branch, _ = prepared
    source = tmp_path / "small.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=5:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True, timeout=30)
    raw = source.read_bytes()
    created = client.post("/api/platform/uploads", json={"branch_id": branch["id"], "name": "small.mp4", "size": len(raw)}, headers=HEADERS)
    assert created.status_code == 201, created.text
    ident = created.json()["id"]
    chunk_size = created.json()["chunk_size"]
    for offset in range(0, len(raw), chunk_size):
        result = client.patch(f"/api/platform/uploads/{ident}", content=raw[offset:offset + chunk_size],
                              headers={**HEADERS, "Upload-Offset": str(offset)})
        assert result.status_code == 200, result.text
    result = client.post(f"/api/platform/uploads/{ident}/finalize", headers=HEADERS)
    assert result.status_code == 200, result.text
    detail = client.get(f"/api/platform/uploads/{ident}").json()
    assert detail["status"] == "uploaded", detail
    assert detail["sha256"] and detail["duration"] > 0
    assert client.get(f"/api/platform/uploads/{ident}/file", headers={"Range": "bytes=0-15"}).status_code == 206
    assert client.get("/api/platform/uploads").json()["total"] == 1
