"""Repoint file-camera SQLite rows after media migration; dry-run unless --apply.

Does not touch RTSP/webcam rows, event rows, or any database location. Before an
apply it makes a verified SQLite backup under backups/storage-migration-20261112.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path, PureWindowsPath

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "docs" / "storage-migration-manifest.json"
BACKUP_DIR = REPO / "backups" / "storage-migration-20261112" / "databases"
DATABASES = {
    "legacy_branch": REPO / "backend" / "branch-exterior-monitoring" / "storage" / "app.db",
    "branch_exterior": REPO / "backend" / "use_cases" / "branch_exterior" / "storage" / "app.db",
    "face_mask": REPO / "backend" / "use_cases" / "face_mask" / "storage" / "app.db",
}


def targets() -> dict[str, Path]:
    rows = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    result = {}
    for row in rows:
        if Path(row["new"]).parent.name == "sample_videos" and Path(row["new"]).is_file():
            name = Path(row["new"]).name.lower()
            target = Path(row["new"]).resolve()
            if name in result and result[name] != target:
                raise RuntimeError(f"Ambiguous destination for {name}")
            result[name] = target
    return result


def migration_rows(connection: sqlite3.Connection, table: str, available: dict[str, Path]) -> list[tuple[str, str]]:
    have = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    if not {"id", "cam_type", "source"}.issubset(have):
        return []
    changes = []
    for camera_id, cam_type, source in connection.execute(f'SELECT id, cam_type, source FROM "{table}"'):
        if cam_type not in {"folder", "upload"} or not source:
            continue
        value = source.replace("\\", "/").lower()
        if "/storage/sample_videos/" not in value and "/storage/uploads/" not in value:
            continue
        if "/face_detection_poc/storage/" in value:
            continue  # already common
        name = PureWindowsPath(source).name.lower()
        target = available.get(name)
        if target and target.is_file() and source != str(target):
            changes.append((str(target), camera_id))
    return changes


def event_rows(connection: sqlite3.Connection, table: str, owner: str) -> list[tuple[str, str, str]]:
    have = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    if not {"id", "snapshot_path", "clip_path"}.issubset(have):
        return []
    changes = []
    for event_id, snapshot, clip in connection.execute(f'SELECT id, snapshot_path, clip_path FROM "{table}"'):
        for column, value, old_prefix, category in (
            ("snapshot_path", snapshot, "snapshots/", "screenshots"),
            ("clip_path", clip, "clips/", "clips"),
        ):
            if not value or not value.startswith(old_prefix):
                continue
            name = value[len(old_prefix):]
            if "/" in name or "\\" in name:
                continue
            relative = f"{category}/{owner}/{name}"
            if (REPO / "storage" / relative).is_file():
                changes.append((column, relative, event_id))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    available = targets()
    for owner, database in DATABASES.items():
        if not database.is_file():
            continue
        connection = sqlite3.connect(database)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            work = [(table, migration_rows(connection, table, available)) for table in ("cameras", "fm_camera") if table in tables]
            evidence = [(table, event_rows(connection, table, owner)) for table in ("events", "fm_concealment_event") if table in tables]
            total = sum(len(rows) for _, rows in work) + sum(len(rows) for _, rows in evidence)
            print(f"{owner}: path_fields_to_repoint={total} mode={'apply' if args.apply else 'dry-run'}")
            if not args.apply or not total:
                continue
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            backup_file = BACKUP_DIR / f"{owner}_app.db"
            if not backup_file.exists():
                backup = sqlite3.connect(backup_file)
                try:
                    connection.backup(backup)
                finally:
                    backup.close()
            with connection:
                for table, rows in work:
                    connection.executemany(f'UPDATE "{table}" SET source=? WHERE id=?', rows)
                for table, rows in evidence:
                    for column, relative, event_id in rows:
                        connection.execute(f'UPDATE "{table}" SET "{column}"=? WHERE id=?', (relative, event_id))
            print(f"{owner}: repointed={total}; backup_verified={backup_file.is_file()}")
        finally:
            connection.close()


if __name__ == "__main__":
    main()
