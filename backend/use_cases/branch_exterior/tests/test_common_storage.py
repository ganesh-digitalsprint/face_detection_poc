from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes.storage import inventory
from fedbank_core.storage import list_media, repo_root, root, safe_path


def test_path_safety_and_listing(monkeypatch, tmp_path):
    monkeypatch.setenv("FEDBANK_STORAGE_ROOT", str(tmp_path))
    video = safe_path("sample_videos/a.mp4")
    video.parent.mkdir()
    video.write_bytes(b"abc")
    details = safe_path("screenshots/face_mask/event.json")
    details.parent.mkdir(parents=True)
    details.write_text("{}")
    assert root() == tmp_path.resolve()
    assert list_media("sample_videos")[0]["size"] == 3
    assert len(list_media("evidence")) == 1
    assert list_media("screenshots") == []
    with pytest.raises(ValueError):
        safe_path("sample_videos/../../app.db")
    with pytest.raises(ValueError):
        safe_path(str(Path(tmp_path) / "app.db"))
    with pytest.raises(ValueError):
        list_media("unknown")


def test_inventory_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("FEDBANK_STORAGE_ROOT", str(tmp_path))
    tmp_path.mkdir(exist_ok=True)
    result = inventory()
    assert result["files"] == []
    assert result["total_bytes"] == 0
    assert result["disk_free_bytes"] > 0


def test_upload_is_listed_and_playable(monkeypatch, tmp_path):
    samples = sorted((repo_root() / "storage" / "sample_videos").glob("*.mp4"), key=lambda item: item.stat().st_size)
    if not samples:
        pytest.skip("No real sample video in this workspace")
    monkeypatch.setenv("FEDBANK_STORAGE_ROOT", str(tmp_path))
    client = TestClient(app)  # no lifespan: this tests storage routes without starting camera workers
    with samples[0].open("rb") as source:
        response = client.post("/api/storage/upload?category=uploads", files={"file": (samples[0].name, source, "video/mp4")})
        assert response.status_code == 201, response.text
        relative = response.json()["path"]
        inventory_response = client.get("/api/storage")
        assert inventory_response.status_code == 200
        assert any(item["path"] == relative for item in inventory_response.json()["files"])
        preview = client.get(f"/api/storage/file/{relative}", headers={"Range": "bytes=0-15"})
        assert preview.status_code == 206
        assert len(preview.content) == 16
