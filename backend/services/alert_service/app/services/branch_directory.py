from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BranchEmailTarget:
    branch_id: str
    branch_name: str
    recipient: str


def load_branch_email(database_path: str, branch_id: str) -> BranchEmailTarget | None:
    path = Path(database_path)
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2) as db:
            row = db.execute("SELECT id,name,email FROM branches WHERE id=?", (branch_id,)).fetchone()
    except (sqlite3.Error, OSError):
        return None
    return BranchEmailTarget(str(row[0]), str(row[1]), str(row[2] or "")) if row else None


def branch_exists(database_path: str, branch_id: str) -> bool:
    path = Path(database_path)
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2) as db:
            return db.execute("SELECT 1 FROM branches WHERE id=?", (branch_id,)).fetchone() is not None
    except (sqlite3.Error, OSError):
        return False
