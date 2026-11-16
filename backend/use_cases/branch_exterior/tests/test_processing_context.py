from types import SimpleNamespace

from app.services.camera_manager import CameraManager


def test_camera_start_snapshots_only_an_explicit_canonical_branch(monkeypatch):
    captured = []
    metadata = {
        "branch_id": "branch-1", "branch_code": "C001", "branch_name": "Central",
        "place_name": "Bengaluru", "region_name": "South", "branch_manager": "Manager",
    }

    monkeypatch.setattr("fedbank_core.events.metadata.resolve_branch_metadata",
                        lambda branch_id: metadata if branch_id == "branch-1" else None)
    monkeypatch.setattr("fedbank_core.events.metadata.enrich_resource_refs", lambda _use_case, refs: dict(refs))

    class Worker:
        def __init__(self, camera, repos, loop, recognizer, branch_metadata):
            captured.append(dict(branch_metadata))
        def start(self): pass
        def stop(self): pass

    monkeypatch.setattr("app.services.camera_manager.CameraWorker", Worker)
    manager = CameraManager()
    manager.bind(SimpleNamespace(), SimpleNamespace())
    camera = SimpleNamespace(id="source-camera", name="Front", enabled=True)

    manager.start(camera, branch_id="branch-1")
    assert captured[-1] == {**metadata, "camera_id": camera.id}
    assert captured[-1]["branch_id"] != camera.id
    manager.start(camera)
    assert captured[-1] == {"camera_id": camera.id}


def test_registered_camera_branch_wins_over_current_ui_scope_and_survives_worker_restart(monkeypatch):
    captured = []
    registry = {"camera_id": "registry-camera", "branch_id": "registered-branch",
        "branch_code": "R001", "branch_name": "Registered", "place_name": "Pune",
        "region_name": "West", "branch_manager": "Manager", "camera_name": "Front"}
    metadata = {key: value for key, value in registry.items() if key != "camera_id"}
    monkeypatch.setattr("fedbank_core.events.metadata.enrich_resource_refs", lambda _use_case, _refs: dict(registry))
    monkeypatch.setattr("fedbank_core.events.metadata.resolve_branch_metadata",
        lambda ident: metadata if ident == "registered-branch" else None)

    class Worker:
        def __init__(self, camera, repos, loop, recognizer, branch_metadata):
            captured.append(dict(branch_metadata))
        def start(self): pass
        def stop(self): pass

    monkeypatch.setattr("app.services.camera_manager.CameraWorker", Worker)
    manager = CameraManager()
    manager.bind(SimpleNamespace(), SimpleNamespace())
    camera = SimpleNamespace(id="registry-camera", name="Fallback", enabled=True)
    manager.start(camera, branch_id="wrong-ui-branch")
    manager.restart(camera)
    assert captured == [registry, registry]
