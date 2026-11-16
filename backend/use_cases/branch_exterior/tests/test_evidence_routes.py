from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes.storage import file as serve_storage_file


@pytest.mark.parametrize(('relative', 'stored'), [
    ('snapshots/legacy.jpg', 'screenshots/branch_exterior/legacy.jpg'),
    ('screenshots/branch_exterior/current.jpg', 'screenshots/branch_exterior/current.jpg'),
    ('clips/legacy.mp4', 'clips/branch_exterior/legacy.mp4'),
    ('clips/branch_exterior/current.mp4', 'clips/branch_exterior/current.mp4'),
])
def test_evidence_route_resolves_supported_owner_paths_inside_storage(tmp_path, monkeypatch, relative, stored):
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path))
    target = tmp_path / stored
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'synthetic evidence')

    response = serve_storage_file(relative)

    assert Path(response.path).resolve() == target.resolve()


@pytest.mark.parametrize('relative', ['../secret.jpg', 'D:/outside.jpg', 'screenshots/branch_exterior/../../outside.jpg'])
def test_evidence_route_rejects_traversal_and_absolute_paths(tmp_path, monkeypatch, relative):
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path))
    with pytest.raises(HTTPException):
        serve_storage_file(relative)
