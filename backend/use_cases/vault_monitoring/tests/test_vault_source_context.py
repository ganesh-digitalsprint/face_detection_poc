import pytest

from app.services import vault_source_context


def test_source_context_resolves_complete_branch_snapshot(monkeypatch):
    snapshot = {"branch_id": "branch-1", "branch_code": "C99127-01",
        "branch_name": "Koramangala", "place_name": "Bengaluru",
        "region_name": "South", "branch_manager": "Manager"}
    monkeypatch.setattr(vault_source_context, "resolve_branch_metadata",
        lambda branch_id: dict(snapshot) if branch_id == "branch-1" else None)

    context = vault_source_context.build_source_context(branch_id="branch-1",
        camera_name="Entrance Camera", source_type="entrance_camera")
    assert context == {**snapshot, "camera_name": "Entrance Camera",
        "source_type": "entrance_camera"}


def test_source_context_allows_missing_branch_and_rejects_unknown(monkeypatch):
    monkeypatch.setattr(vault_source_context, "resolve_branch_metadata", lambda _branch_id: None)
    assert vault_source_context.build_source_context(branch_id=None,
        camera_name="Vault Room Camera", source_type="browser_webcam") == {
            "camera_name": "Vault Room Camera", "source_type": "browser_webcam"}
    with pytest.raises(ValueError, match="Branch Management branch was not found"):
        vault_source_context.build_source_context(branch_id="missing",
            camera_name="Vault Room Camera", source_type="browser_webcam")
