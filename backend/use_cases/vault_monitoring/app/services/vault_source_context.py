"""Immutable, non-sensitive source context for Vault sessions and cameras."""
from __future__ import annotations

from fedbank_core.events.metadata import resolve_branch_metadata, safe_reference


def build_source_context(*, branch_id: str | None, camera_name: str,
                         source_type: str, source_id: str | None = None) -> dict:
    """Resolve one existing branch and return a snapshot safe for JSON storage."""
    branch = resolve_branch_metadata(branch_id) if branch_id else {}
    if branch_id and branch is None:
        raise ValueError("Selected Branch Management branch was not found")
    context = {
        **(branch or {}),
        "camera_name": safe_reference(camera_name) or "Vault Camera",
        "source_type": safe_reference(source_type),
    }
    if source_id := safe_reference(source_id):
        context["source_id"] = source_id
    return {key: value for key, value in context.items() if value is not None}
