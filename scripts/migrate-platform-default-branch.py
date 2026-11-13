"""Dry-run by default; --apply imports legacy camera identities into a Default branch.

Legacy databases are read-only and keep their IDs/rows. Only the new platform DB is
written. A SQLite backup of that DB is made before any update to an existing file.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "use_cases" / "branch_exterior"))
from app.api.routes.platform import _db_path, database  # noqa: E402

SOURCES = (("branch_exterior", "cameras"), ("face_mask", "fm_camera"),
           ("vault_access", "registry_cameras"))


def legacy_rows():
    for use_case, table in SOURCES:
        folder = "vault_monitoring" if use_case == "vault_access" else use_case
        path = REPO / "backend" / "use_cases" / folder / "storage" / "app.db"
        if not path.is_file():
            continue
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
            for ident, name in conn.execute(f"SELECT id,name FROM {table}"):
                yield use_case, str(ident), str(name)


def run(apply: bool) -> dict:
    rows = list(legacy_rows())
    path = _db_path()
    if apply and path.is_file():
        backup = REPO / "backups" / "platform-migration" / f"platform-{datetime.now():%Y%m%d-%H%M%S}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
    if not apply:
        return {"mode": "dry-run", "legacy_camera_rows": len(rows), "platform_db_exists": path.is_file()}
    zone_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "fedbank/default-zone"))
    city_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "fedbank/default-city"))
    branch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "fedbank/default-branch"))
    imported = 0
    with database() as conn:
        conn.execute("INSERT OR IGNORE INTO zones(id,name) VALUES(?,?)", (zone_id, "Default"))
        conn.execute("INSERT OR IGNORE INTO cities(id,zone_id,name) VALUES(?,?,?)", (city_id, zone_id, "Default"))
        conn.execute("INSERT OR IGNORE INTO branches(id,city_id,code,name) VALUES(?,?,?,?)",
                     (branch_id, city_id, "DEFAULT-01", "Default branch"))
        for use_case, legacy_id, name in rows:
            if conn.execute("SELECT 1 FROM legacy_camera_links WHERE use_case=? AND legacy_id=?", (use_case, legacy_id)).fetchone():
                continue
            number = conn.execute("SELECT COALESCE(MAX(channel_no),0)+1 FROM cameras WHERE branch_id=?", (branch_id,)).fetchone()[0]
            ident = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fedbank/{use_case}/{legacy_id}"))
            conn.execute("INSERT INTO cameras(id,branch_id,channel_no,code,name) VALUES(?,?,?,?,?)",
                         (ident, branch_id, number, f"CH-{number:02d}", name))
            conn.execute("INSERT INTO camera_use_cases(camera_id,use_case) VALUES(?,?)", (ident, use_case))
            conn.execute("INSERT INTO legacy_camera_links(use_case,legacy_id,branch_id) VALUES(?,?,?)",
                         (use_case, legacy_id, branch_id))
            imported += 1
    return {"mode": "apply", "legacy_camera_rows": len(rows), "imported": imported}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Back up and import legacy cameras")
    print(run(parser.parse_args().apply))
