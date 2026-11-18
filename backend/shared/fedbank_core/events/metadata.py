"""Optional public identifiers from explicit platform registry links; never infer a branch."""
import os
from pathlib import Path
import sqlite3

from fedbank_core.storage import repo_root


def safe_reference(value, limit=128):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return None
    lowered = value.lower()
    if "://" in value or "@" in value or any(term in lowered for term in
            ("password=", "token=", "api_key=", "secret=", "signature=")):
        return None
    return value


def resolve_branch_metadata(branch_id):
    """Read one existing Branch Management hierarchy snapshot without creating data."""
    branch_id = safe_reference(branch_id)
    if not branch_id:
        return None
    path = Path(os.environ.get("FEDBANK_PLATFORM_DB_PATH") or
        repo_root() / "backend/services/platform_data/platform.db")
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1) as db:
            row = db.execute("SELECT b.id,b.code,b.name,ci.name,z.name,b.manager FROM branches b "
                "JOIN cities ci ON ci.id=b.city_id JOIN zones z ON z.id=ci.zone_id WHERE b.id=?",
                (branch_id,)).fetchone()
        if row is None:
            return None
        return {key: value for key, raw in zip(
            ("branch_id", "branch_code", "branch_name", "place_name", "region_name", "branch_manager"), row)
            if (value := safe_reference(raw))}
    except (sqlite3.Error, OSError):
        return None


def resolve_branch_camera_metadata(branch_id, camera_id, *, use_case="grill_gate"):
    """Resolve a camera only when the platform registry links it to this branch/use case."""
    branch_id, camera_id = safe_reference(branch_id), safe_reference(camera_id)
    if not branch_id or not camera_id:
        return None
    path = Path(os.environ.get("FEDBANK_PLATFORM_DB_PATH") or
        repo_root() / "backend/services/platform_data/platform.db")
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1) as db:
            row = db.execute(
                "SELECT c.id,c.name FROM cameras c JOIN camera_use_cases u ON u.camera_id=c.id "
                "WHERE c.id=? AND c.branch_id=? AND u.use_case=?",
                (camera_id, branch_id, use_case),
            ).fetchone()
        if row is None:
            return None
        return {"camera_id": row[0], "camera_name": safe_reference(row[1])}
    except (sqlite3.Error, OSError):
        return None


def enrich_resource_refs(use_case, refs):
    """Keep source camera IDs. Legacy links identify a branch, not a replacement camera.

    The platform DB is optional and read-only here. Absence, old schemas and lock
    contention must not prevent source publication or create a default branch.
    """
    refs = dict(refs)
    camera_id = safe_reference(refs.get("registry_camera_id") or refs.get("camera_id"))
    if not camera_id:
        return refs
    path = Path(os.environ.get("FEDBANK_PLATFORM_DB_PATH") or
        repo_root() / "backend/services/platform_data/platform.db")
    if not path.is_file():
        return refs
    platform_case = "vault_access" if use_case == "vault_monitoring" else use_case
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1) as db:
            if use_case in {"grill_gate", "branch_exterior"}:
                try:
                    row = db.execute("SELECT b.id,b.code,b.name,c.name,ci.name,z.name,b.manager FROM cameras c "
                        "JOIN branches b ON b.id=c.branch_id JOIN cities ci ON ci.id=b.city_id "
                        "JOIN zones z ON z.id=ci.zone_id JOIN camera_use_cases u ON u.camera_id=c.id "
                        "WHERE c.id=? AND u.use_case=?", (camera_id, platform_case)).fetchone()
                except sqlite3.Error:
                    if use_case != "branch_exterior":
                        raise
                    row = db.execute("SELECT b.id,NULL,b.name,c.name,NULL,NULL,NULL FROM cameras c "
                        "JOIN branches b ON b.id=c.branch_id JOIN camera_use_cases u ON u.camera_id=c.id "
                        "WHERE c.id=? AND u.use_case=?", (camera_id, platform_case)).fetchone()
            else:
                row = db.execute("SELECT b.id,b.name,c.name FROM cameras c "
                    "JOIN branches b ON b.id=c.branch_id JOIN camera_use_cases u ON u.camera_id=c.id "
                    "WHERE c.id=? AND u.use_case=?", (camera_id, platform_case)).fetchone()
            if row is None:
                if use_case in {"grill_gate", "branch_exterior"}:
                    try:
                        row = db.execute("SELECT b.id,b.code,b.name,NULL,ci.name,z.name,b.manager "
                            "FROM legacy_camera_links l JOIN branches b ON b.id=l.branch_id "
                            "JOIN cities ci ON ci.id=b.city_id JOIN zones z ON z.id=ci.zone_id "
                            "WHERE l.legacy_id=? AND l.use_case=?", (camera_id, platform_case)).fetchone()
                    except sqlite3.Error:
                        if use_case != "branch_exterior":
                            raise
                        row = db.execute("SELECT b.id,NULL,b.name,NULL,NULL,NULL,NULL "
                            "FROM legacy_camera_links l JOIN branches b ON b.id=l.branch_id "
                            "WHERE l.legacy_id=? AND l.use_case=?", (camera_id, platform_case)).fetchone()
                else:
                    row = db.execute("SELECT b.id,b.name,NULL FROM legacy_camera_links l "
                        "JOIN branches b ON b.id=l.branch_id WHERE l.legacy_id=? AND l.use_case=?",
                        (camera_id, platform_case)).fetchone()
        if row and (not refs.get("branch_id") or refs["branch_id"] == row[0]):
            keys = (("branch_id", "branch_code", "branch_name", "camera_name", "place_name", "region_name", "branch_manager")
                    if use_case in {"grill_gate", "branch_exterior"} else ("branch_id", "branch_name", "camera_name"))
            for key, value in zip(keys, row):
                value = safe_reference(value)
                if value and not refs.get(key):
                    refs[key] = value
    except (sqlite3.Error, OSError):
        pass
    return refs
