"""Read-only checks for existing local evidence, using the deployed storage resolver."""
from pathlib import Path
from fedbank_core.storage import root, legacy_resolve


def media_path(relative, owner):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    try:
        base = root().resolve()
        path = (base / relative).resolve()
        if not path.is_relative_to(base):
            return None
        if not path.is_file():
            path = legacy_resolve(relative, owner)
        if path is None or not path.resolve().is_relative_to(base) or not path.is_file():
            return None
        # Do not report unreadable or empty files as available evidence.
        with path.open('rb') as stream:
            return path if stream.read(1) else None
    except (OSError, ValueError):
        return None


def evidence_metadata(refs, pending=False, *, failed=False, unavailable_reason=None):
    snapshots = sum(ref.get('type') == 'snapshot' for ref in refs)
    clips = sum(ref.get('type') == 'clip' for ref in refs)
    result = {'evidence_status': 'CAPTURED' if refs else 'PENDING' if pending else 'FAILED' if failed else 'UNAVAILABLE',
        'evidence_count': len(refs), 'snapshot_count': snapshots, 'clip_count': clips}
    if not refs and unavailable_reason:
        result['evidence_unavailable_reason'] = str(unavailable_reason)[:160]
    return result
