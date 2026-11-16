"""Session-time source snapshots for Grill Gate camera alerts."""
from collections.abc import Callable

from app.db.models.camera_registry import CameraSource, CameraUseCaseAssignment, RegistryCamera
from fedbank_core.events.metadata import enrich_resource_refs, resolve_branch_metadata, safe_reference


def live_alert_source_context(session_factory: Callable, camera_id: str, assignment_id: str) -> dict:
    """Snapshot a configured camera and its canonical branch when a live session starts."""
    camera_id = safe_reference(str(camera_id))
    assignment_id = safe_reference(str(assignment_id))
    if not camera_id or not assignment_id:
        return {}
    with session_factory() as db:
        camera = db.get(RegistryCamera, camera_id)
        if camera is None:
            return {"camera_id": camera_id, "assignment_id": assignment_id}
        assignment = db.get(CameraUseCaseAssignment, assignment_id)
        source_id = ((assignment.configuration or {}).get("source_id")
                     if assignment is not None and str(assignment.camera_id) == camera_id
                     and assignment.use_case == "grill_gate" else None)
        source = db.get(CameraSource, str(source_id)) if source_id else None
        if source is not None and (str(source.camera_id) != camera_id or not source.is_active):
            source = None
        refs = enrich_resource_refs("grill_gate", {"camera_id": camera_id,
            "registry_camera_id": camera_id, "assignment_id": assignment_id})
        branch = resolve_branch_metadata(refs.get("branch_id")) if refs.get("branch_id") else None
        snapshot = {"camera_id": camera_id, "registry_camera_id": camera_id,
            "assignment_id": assignment_id, "camera_name": safe_reference(camera.name),
            "source_type": (safe_reference(source.source_type) if source is not None else None)
                or "REGISTERED_CAMERA"}
        if branch:
            snapshot.update(branch)
        return snapshot
