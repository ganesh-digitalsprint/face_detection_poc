"""Look inside the events database from the command line - nothing to install, no credentials.

It opens backend/storage/app.db READ-ONLY with Python's built-in sqlite3, so it is safe to run
while the server is running.

  uv run python scripts/db_viewer.py tables                       tables and row counts
  uv run python scripts/db_viewer.py schema                       columns of every table
  uv run python scripts/db_viewer.py summary                      events per type / severity / camera
  uv run python scripts/db_viewer.py events                       latest 20 events
  uv run python scripts/db_viewer.py events --limit 50 --severity high
  uv run python scripts/db_viewer.py events --kind snatch_flee    (kinds: weapon, fighting, fallen, snatch_flee,
                                                                   vehicle_escape, violent_action, scanning,
                                                                   gate_tampering, atm_group, group, running, jumping)
  uv run python scripts/db_viewer.py events --camera "Video 16863"
  uv run python scripts/db_viewer.py event 3fa9                   everything about one event (id prefix is enough)
  uv run python scripts/db_viewer.py sql "SELECT severity, COUNT(*) FROM events GROUP BY severity"
  uv run python scripts/db_viewer.py export events.csv            all events -> CSV (opens in Excel)

Handy: the AI's details live in the `meta` JSON column; pull a field out with
  json_extract(meta, '$.kind')    json_extract(meta, '$.method')    json_extract(meta, '$.agitation')
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "storage" / "app.db"

KIND = "COALESCE(json_extract(meta, '$.kind'), scenario)"


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"Database not found: {path}\nStart the server once (it creates it) or pass --db <path>.")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def show(rows, headers=None, max_w: int = 46) -> None:
    rows = [tuple(r) for r in rows]
    if headers is None:
        headers = [f"col{i}" for i in range(len(rows[0]))] if rows else []
    if not rows:
        print("(no rows)")
        return
    cut = lambda v: (str(v) if v is not None else "")[: max_w - 1] + ("…" if len(str(v)) > max_w else "")  # noqa: E731
    cells = [[cut(v) for v in r] for r in rows]
    widths = [max(len(str(h)), *(len(c[i]) for c in cells)) for i, h in enumerate(headers)]
    print("  ".join(str(h).ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for c in cells:
        print("  ".join(v.ljust(w) for v, w in zip(c, widths)))
    print(f"\n{len(rows)} row(s)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tables")
    sub.add_parser("schema")
    sub.add_parser("summary")
    e = sub.add_parser("events")
    e.add_argument("--limit", type=int, default=20)
    e.add_argument("--severity")
    e.add_argument("--kind")
    e.add_argument("--camera")
    one = sub.add_parser("event")
    one.add_argument("id")
    q = sub.add_parser("sql")
    q.add_argument("query")
    x = sub.add_parser("export")
    x.add_argument("file")
    a = ap.parse_args()
    con = connect(a.db)

    if a.cmd == "tables":
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        show([(n, con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]) for n in names], ["table", "rows"])
    elif a.cmd == "schema":
        for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            print(f"\n[{n}]")
            show([(r["name"], r["type"]) for r in con.execute(f'PRAGMA table_info("{n}")')], ["column", "type"])
    elif a.cmd == "summary":
        print("== events by type ==")
        show(con.execute(f"SELECT {KIND} AS type, COUNT(*) n FROM events GROUP BY 1 ORDER BY n DESC").fetchall(), ["type", "events"])
        print("\n== events by severity ==")
        show(con.execute("SELECT severity, COUNT(*) n FROM events GROUP BY 1 ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END").fetchall(), ["severity", "events"])
        print("\n== events by camera ==")
        show(con.execute("SELECT camera_name, COUNT(*) n, SUM(snapshot_path <> '') AS with_snapshot, SUM(clip_path <> '') AS with_clip FROM events GROUP BY 1 ORDER BY n DESC").fetchall(), ["camera", "events", "with_snapshot", "with_clip"])
    elif a.cmd == "events":
        where, args = [], []
        if a.severity:
            where.append("severity = ?"); args.append(a.severity.lower())
        if a.kind:
            where.append(f"{KIND} = ?"); args.append(a.kind)
        if a.camera:
            where.append("camera_name LIKE ?"); args.append(f"%{a.camera}%")
        sql = (f"SELECT substr(id,1,8) AS id, substr(created_at,1,19) AS time, camera_name, {KIND} AS type, severity, "
               f"ROUND(confidence,2) AS conf, status, message FROM events "
               f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY created_at DESC LIMIT ?")
        show(con.execute(sql, args + [a.limit]).fetchall(), ["id", "time", "camera", "type", "severity", "conf", "status", "message"], max_w=60)
    elif a.cmd == "event":
        rows = con.execute("SELECT * FROM events WHERE id LIKE ? LIMIT 2", (a.id + "%",)).fetchall()
        if not rows:
            sys.exit("No event with that id.")
        if len(rows) > 1:
            sys.exit("More than one event starts with that id - type a few more characters.")
        for k in rows[0].keys():
            v = rows[0][k]
            if k == "meta" and v:
                v = json.dumps(json.loads(v), indent=2)
            print(f"{k:16} {v}")
    elif a.cmd == "sql":
        if not a.query.strip().lower().startswith(("select", "with", "pragma")):
            sys.exit("Only SELECT / WITH / PRAGMA queries are allowed here (the database is opened read-only).")
        cur = con.execute(a.query)
        show(cur.fetchall(), [d[0] for d in cur.description] if cur.description else None)
    elif a.cmd == "export":
        cur = con.execute(f"SELECT *, {KIND} AS kind FROM events ORDER BY created_at")
        with open(a.file, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            n = 0
            for r in cur:
                w.writerow(list(r)); n += 1
        print(f"Wrote {n} events to {a.file}")


if __name__ == "__main__":
    main()
