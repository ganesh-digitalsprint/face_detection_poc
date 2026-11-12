"""Shared branch/camera registry hosted by Branch 8011, separate from its use-case DB.

Write operations fail closed without server-side credentials. No endpoint returns RTSP
credentials; a recorder's encrypted secret is only decrypted in the probe worker.
"""
from __future__ import annotations

import ipaddress
from datetime import datetime
import multiprocessing
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit
import json
import socket
import xml.etree.ElementTree as ET

from cryptography.fernet import Fernet
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.core import paths as _paths  # sets the shared-library import path
from fedbank_core.storage import repo_root

router = APIRouter(prefix="/platform", tags=["platform"])
DB_PATH = repo_root() / "backend" / "services" / "platform_data" / "platform.db"
USE_CASES = {"vault_access", "branch_exterior", "grill_gate", "face_mask"}
CODE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{2,38}$")


def _db_path() -> Path:
    return Path(os.environ.get("FEDBANK_PLATFORM_DB_PATH") or DB_PATH)


@contextmanager
def database():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        with sqlite3.connect(path) as existing:
            has_uploads = existing.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_uploads'").fetchone()
            recorder_exists = existing.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recorders'").fetchone()
            has_scheme = not recorder_exists or any(row[1] == "scheme" for row in existing.execute("PRAGMA table_info(recorders)"))
            if not has_uploads or not has_scheme:
                backup = repo_root() / "backups" / "platform-migration" / f"platform-schema-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
                backup.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(backup) as target:
                    existing.backup(target)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS zones (
          id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS cities (
          id TEXT PRIMARY KEY, zone_id TEXT NOT NULL REFERENCES zones(id),
          name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(zone_id,name));
        CREATE TABLE IF NOT EXISTS branches (
          id TEXT PRIMARY KEY, city_id TEXT NOT NULL REFERENCES cities(id),
          code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          address TEXT NOT NULL DEFAULT '', pincode TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
          manager TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CHECK(status IN ('active','inactive')));
        CREATE TABLE IF NOT EXISTS recorders (
          id TEXT PRIMARY KEY, branch_id TEXT NOT NULL REFERENCES branches(id), mode TEXT NOT NULL,
          host TEXT NOT NULL, rtsp_port INTEGER NOT NULL, scheme TEXT NOT NULL DEFAULT 'rtsp', username TEXT NOT NULL DEFAULT '',
          password_encrypted TEXT NOT NULL DEFAULT '', path_template TEXT NOT NULL,
          stream INTEGER NOT NULL DEFAULT 1, transport TEXT NOT NULL DEFAULT 'tcp',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS cameras (
          id TEXT PRIMARY KEY, branch_id TEXT NOT NULL REFERENCES branches(id), recorder_id TEXT REFERENCES recorders(id),
          channel_no INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
          width INTEGER, height INTEGER, codec TEXT, fps REAL, status TEXT NOT NULL DEFAULT 'offline',
          last_seen TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(branch_id,code));
        CREATE TABLE IF NOT EXISTS camera_use_cases (
          camera_id TEXT NOT NULL REFERENCES cameras(id), use_case TEXT NOT NULL,
          PRIMARY KEY(camera_id,use_case));
        CREATE TABLE IF NOT EXISTS legacy_camera_links (
          use_case TEXT NOT NULL, legacy_id TEXT NOT NULL, branch_id TEXT NOT NULL REFERENCES branches(id),
          PRIMARY KEY(use_case,legacy_id));
        CREATE TABLE IF NOT EXISTS video_uploads (
          id TEXT PRIMARY KEY, branch_id TEXT NOT NULL REFERENCES branches(id), camera_id TEXT REFERENCES cameras(id),
          use_case TEXT, original_name TEXT NOT NULL, stored_path TEXT NOT NULL UNIQUE,
          size INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0, sha256 TEXT,
          status TEXT NOT NULL DEFAULT 'uploading', error TEXT,
          duration REAL, width INTEGER, height INTEGER, fps REAL, codec TEXT,
          thumbnail_path TEXT, proxy_path TEXT, uploaded_by TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS ix_cities_zone ON cities(zone_id);
        CREATE INDEX IF NOT EXISTS ix_branches_city ON branches(city_id);
        CREATE INDEX IF NOT EXISTS ix_cameras_branch ON cameras(branch_id);
        """)
        if not any(row[1] == "scheme" for row in connection.execute("PRAGMA table_info(recorders)")):
            connection.execute("ALTER TABLE recorders ADD COLUMN scheme TEXT NOT NULL DEFAULT 'rtsp'")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _admin(x_platform_admin_key: str = Header(default="")) -> None:
    expected = os.environ.get("FEDBANK_PLATFORM_ADMIN_KEY", "")
    if not expected:
        raise HTTPException(503, "Platform writes require a server-side admin key")
    if not secrets.compare_digest(expected, x_platform_admin_key):
        raise HTTPException(403, "Admin permission required")


def _cipher() -> Fernet:
    key = os.environ.get("FEDBANK_PLATFORM_FERNET_KEY", "")
    if not key:
        raise HTTPException(503, "Recorder encryption key is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "Recorder encryption key is invalid") from exc


def validate_host(host: str) -> str:
    value = host.strip().strip("[]").lower()
    if not value or any(char in value for char in "/\\@?#%"):
        raise ValueError("Invalid RTSP host")
    try:
        address = ipaddress.ip_address(value)
        if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
            raise ValueError("RTSP host is not allowed")
        if not (address.is_private or address.is_loopback):
            raise ValueError("RTSP host must be private or loopback")
        return value
    except ValueError as exc:
        if "RTSP host" in str(exc):
            raise
        allowed = {name.strip().lower() for name in os.environ.get("FEDBANK_RTSP_HOST_ALLOWLIST", "").split(",") if name.strip()}
        if value not in allowed:
            raise ValueError("RTSP hostname is not allowlisted") from exc
        return value


def validate_rtsp_url(value: str) -> tuple[str, str, int, str, str, str]:
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"rtsp", "rtsps"} or not parts.hostname:
            raise ValueError("Only RTSP/RTSPS camera URLs are allowed")
        host = validate_host(parts.hostname)
        port = parts.port or 554
        if not 1 <= port <= 65535:
            raise ValueError("Invalid RTSP port")
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return parts.scheme.lower(), host, port, path, parts.username or "", parts.password or ""
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid or disallowed RTSP URL") from exc


def public_recorder(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in ("id", "branch_id", "mode", "host", "rtsp_port", "scheme", "username", "stream", "transport")} | {"has_password": bool(row["password_encrypted"])}


def _template(key: str, custom: str = "") -> str:
    config = json.loads((repo_root() / "config" / "rtsp_templates.json").read_text(encoding="utf-8"))
    if key == "generic":
        path = custom
    else:
        path = config.get(key, "")
    if not path.startswith("/") or any(mark in path.lower() for mark in ("..", "@", "\\", "\n", "\r")):
        raise ValueError("Invalid RTSP template")
    return path


def _camera_url(recorder: "RecorderCreate", channel: int) -> str:
    template = _template(recorder.template_key, recorder.custom_path)
    path = template.format(channel=channel, stream=recorder.stream)
    credentials = quote(recorder.username, safe="")
    if recorder.password:
        credentials += ":" + quote(recorder.password, safe="")
    authority = (credentials + "@") if credentials else ""
    host = f"[{recorder.host}]" if ":" in recorder.host else recorder.host
    return f"{recorder.scheme}://{authority}{host}:{recorder.rtsp_port}{path}"


def _probe_worker(url: str, timeout_ms: int, output) -> None:
    """Separate process makes a hard timeout possible even when OpenCV blocks in FFmpeg."""
    os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
    try:
        import cv2
        start = time.monotonic()
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms,
                                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms])
        try:
            if not capture.isOpened():
                output.put({"ok": False, "reason": "Connection failed, timed out, or authentication was rejected"})
                return
            good, frame = capture.read()
            if not good or frame is None:
                output.put({"ok": False, "reason": "Connected but no video frame was received"})
                return
            output.put({"ok": True, "latency_ms": round((time.monotonic() - start) * 1000),
                        "width": int(frame.shape[1]), "height": int(frame.shape[0]),
                        "fps": round(capture.get(cv2.CAP_PROP_FPS), 2),
                        "codec": "unknown"})
        finally:
            capture.release()
    except Exception:
        output.put({"ok": False, "reason": "Unable to open RTSP video"})


def probe_url(url: str, timeout_ms: int) -> dict:
    ctx = multiprocessing.get_context("spawn")
    output = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_probe_worker, args=(url, timeout_ms, output), daemon=True)
    proc.start()
    proc.join(timeout_ms / 1000 + 1)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        return {"ok": False, "reason": "RTSP connection timed out"}
    try:
        return output.get(timeout=0.5)
    except Exception:
        return {"ok": False, "reason": "RTSP probe did not return a result"}


def discover_onvif(timeout_seconds: float = 2.0) -> list[dict]:
    """Best-effort WS-Discovery multicast. A missing reply is an honest empty result."""
    probe = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
             'xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
             'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
             '<s:Header><a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>'
             f'<a:MessageID>urn:uuid:{uuid.uuid4()}</a:MessageID>'
             '<a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To></s:Header>'
             '<s:Body><d:Probe/></s:Body></s:Envelope>')
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.25)
        sock.sendto(probe.encode(), ("239.255.255.250", 3702))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                packet, sender = sock.recvfrom(16384)
                validate_host(sender[0])
                root = ET.fromstring(packet)
                namespace = {"d": "http://schemas.xmlsoap.org/ws/2005/04/discovery"}
                addresses = [node.text for node in root.findall(".//d:XAddrs", namespace) if node.text]
                found[sender[0]] = {"host": sender[0], "addresses": addresses, "model": None}
            except (socket.timeout, ValueError, ET.ParseError):
                continue
    return list(found.values())


def _one(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> dict:
    row = conn.execute(sql, args).fetchone()
    if row is None:
        raise HTTPException(404, "Record not found")
    return dict(row)


class Named(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class CityCreate(Named):
    zone_id: str


class BranchCreate(Named):
    city_id: str
    code: str
    status: str = "active"
    address: str = ""
    pincode: str = ""
    timezone: str = "Asia/Kolkata"
    manager: str = ""
    phone: str = ""
    email: str = ""

    @field_validator("code")
    @classmethod
    def code_valid(cls, value: str) -> str:
        if not CODE.fullmatch(value):
            raise ValueError("Branch code must be 3–39 letters, digits or dashes and start with a letter")
        return value.upper()

    @field_validator("status")
    @classmethod
    def status_valid(cls, value: str) -> str:
        if value not in {"active", "inactive"}:
            raise ValueError("Status must be active or inactive")
        return value

    @field_validator("pincode")
    @classmethod
    def pincode_valid(cls, value: str) -> str:
        if value and not re.fullmatch(r"[0-9]{6}", value):
            raise ValueError("Pincode must be six digits")
        return value


class RecorderCreate(BaseModel):
    branch_id: str
    mode: str = "nvr"
    scheme: str = "rtsp"
    host: str = ""
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    username: str = ""
    password: str = ""
    full_url: str = ""
    template_key: str = "hikvision"
    custom_path: str = ""
    stream: int = Field(default=1, ge=1, le=2)
    transport: str = "tcp"

    @field_validator("scheme")
    @classmethod
    def scheme_valid(cls, value: str) -> str:
        if value not in {"rtsp", "rtsps"}:
            raise ValueError("Only RTSP and RTSPS are allowed")
        return value


class CameraCreate(BaseModel):
    channel_no: int = Field(ge=1, le=999)
    name: str = Field(min_length=1, max_length=120)
    use_case: str
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    fps: float | None = None


class CameraBatch(BaseModel):
    recorder: RecorderCreate
    cameras: list[CameraCreate] = Field(min_length=1, max_length=64)


@router.get("/health")
def health():
    with database():
        return {"status": "ok", "admin_configured": bool(os.environ.get("FEDBANK_PLATFORM_ADMIN_KEY")),
                "encryption_configured": bool(os.environ.get("FEDBANK_PLATFORM_FERNET_KEY"))}


@router.get("/rtsp-templates")
def templates():
    return json.loads((repo_root() / "config" / "rtsp_templates.json").read_text(encoding="utf-8"))


@router.post("/recorders/test")
def test_recorder(payload: RecorderCreate, x_platform_admin_key: str = Header(default=""),
                  timeout_seconds: int = Query(3, ge=1, le=10), max_channels: int = Query(32, ge=1, le=64)):
    _admin(x_platform_admin_key)
    if payload.full_url:
        try:
            scheme, host, port, path, user, password = validate_rtsp_url(payload.full_url)
            payload = payload.model_copy(update={"scheme": scheme, "host": host, "rtsp_port": port, "template_key": "generic",
                                                "custom_path": path, "username": user or payload.username,
                                                "password": password or payload.password})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    try:
        validate_host(payload.host)
        _template(payload.template_key, payload.custom_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    found = []
    failures = 0
    count = 1 if payload.mode == "single" else max_channels
    for channel in range(1, count + 1):
        try:
            result = probe_url(_camera_url(payload, channel), timeout_seconds * 1000)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "Invalid RTSP path template") from exc
        if result["ok"]:
            found.append({"channel_no": channel, **result})
            failures = 0
        else:
            failures += 1
            if failures >= 3:
                break
    return {"connected": bool(found), "channels": found, "channel_count": len(found),
            "reason": None if found else "No working channel found; check host, credentials and stream path"}


@router.post("/onvif/discover")
def onvif_discover(x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    try:
        devices = discover_onvif()
    except OSError:
        devices = []
    return {"devices": devices, "beta": True,
            "hint": "No devices answered WS-Discovery; check that the server and cameras share a multicast-enabled network" if not devices else None}


@router.get("/zones")
def zones():
    with database() as conn:
        rows = conn.execute("SELECT z.*, COUNT(DISTINCT c.id) city_count, COUNT(DISTINCT b.id) branch_count FROM zones z LEFT JOIN cities c ON c.zone_id=z.id LEFT JOIN branches b ON b.city_id=c.id GROUP BY z.id ORDER BY z.name")
        return [dict(row) for row in rows]


@router.post("/zones", status_code=201)
def create_zone(payload: Named, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        try:
            ident = str(uuid.uuid4())
            conn.execute("INSERT INTO zones(id,name) VALUES(?,?)", (ident, payload.name.strip()))
            return _one(conn, "SELECT * FROM zones WHERE id=?", (ident,))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Zone already exists") from exc


@router.get("/cities")
def cities(zone_id: str):
    with database() as conn:
        return [dict(row) for row in conn.execute("SELECT c.*, COUNT(b.id) branch_count FROM cities c LEFT JOIN branches b ON b.city_id=c.id WHERE c.zone_id=? GROUP BY c.id ORDER BY c.name", (zone_id,))]


@router.post("/cities", status_code=201)
def create_city(payload: CityCreate, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        _one(conn, "SELECT id FROM zones WHERE id=?", (payload.zone_id,))
        try:
            ident = str(uuid.uuid4())
            conn.execute("INSERT INTO cities(id,zone_id,name) VALUES(?,?,?)", (ident, payload.zone_id, payload.name.strip()))
            return _one(conn, "SELECT * FROM cities WHERE id=?", (ident,))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "City already exists in this zone") from exc


@router.get("/branches")
def branches(city_id: str, search: str = "", offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    with database() as conn:
        term = f"%{search.strip()}%"
        args = (city_id, term, term)
        count = conn.execute("SELECT COUNT(*) FROM branches WHERE city_id=? AND (name LIKE ? OR code LIKE ?)", args).fetchone()[0]
        rows = conn.execute("SELECT b.*, COUNT(c.id) camera_count FROM branches b LEFT JOIN cameras c ON c.branch_id=b.id WHERE b.city_id=? AND (b.name LIKE ? OR b.code LIKE ?) GROUP BY b.id ORDER BY b.name LIMIT ? OFFSET ?", args + (limit, offset))
        return {"items": [dict(row) | {"open_alert_count": None} for row in rows], "total": count, "offset": offset, "limit": limit}


@router.get("/branches/next-code")
def next_code():
    with database() as conn:
        codes = [row[0] for row in conn.execute("SELECT code FROM branches WHERE code LIKE 'C99127-%'")]
    numbers = [int(code.split("-")[-1]) for code in codes if re.fullmatch(r"C99127-[0-9]+", code)]
    return {"code": f"C99127-{max(numbers, default=0) + 1:02d}"}


@router.get("/branches/search")
def search_branches(query: str = "", limit: int = Query(20, ge=1, le=100)):
    term = f"%{query.strip()}%"
    with database() as conn:
        rows = conn.execute("SELECT b.id,b.code,b.name,b.status,c.name city_name,z.name zone_name FROM branches b JOIN cities c ON c.id=b.city_id JOIN zones z ON z.id=c.zone_id WHERE b.name LIKE ? OR b.code LIKE ? ORDER BY b.name LIMIT ?", (term, term, limit))
        return [dict(row) for row in rows]


@router.get("/branches/{branch_id}")
def branch(branch_id: str):
    with database() as conn:
        return _one(conn, "SELECT * FROM branches WHERE id=?", (branch_id,))


@router.post("/branches", status_code=201)
def create_branch(payload: BranchCreate, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        _one(conn, "SELECT id FROM cities WHERE id=?", (payload.city_id,))
        try:
            ident = str(uuid.uuid4())
            conn.execute("INSERT INTO branches(id,city_id,code,name,status,address,pincode,timezone,manager,phone,email) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (ident, payload.city_id, payload.code, payload.name.strip(), payload.status, payload.address,
                          payload.pincode, payload.timezone, payload.manager, payload.phone, payload.email))
            return _one(conn, "SELECT * FROM branches WHERE id=?", (ident,))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Branch code already exists") from exc


@router.get("/branches/{branch_id}/cameras")
def cameras(branch_id: str):
    with database() as conn:
        _one(conn, "SELECT id FROM branches WHERE id=?", (branch_id,))
        return [dict(row) for row in conn.execute("SELECT c.*, group_concat(u.use_case) use_cases FROM cameras c LEFT JOIN camera_use_cases u ON u.camera_id=c.id WHERE c.branch_id=? GROUP BY c.id ORDER BY c.channel_no", (branch_id,))]


@router.get("/branches/{branch_id}/recorders")
def recorders(branch_id: str):
    with database() as conn:
        return [public_recorder(row) for row in conn.execute("SELECT * FROM recorders WHERE branch_id=?", (branch_id,))]


@router.post("/cameras/bulk", status_code=201)
def create_cameras(payload: CameraBatch, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    recorder = payload.recorder
    if recorder.mode not in {"nvr", "single", "onvif"} or recorder.transport not in {"tcp", "udp"}:
        raise HTTPException(422, "Unsupported recorder mode or transport")
    if recorder.full_url:
        try:
            scheme, host, port, path, user, password = validate_rtsp_url(recorder.full_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        recorder = recorder.model_copy(update={"scheme": scheme, "host": host, "rtsp_port": port, "template_key": "generic", "custom_path": path,
                                               "username": user or recorder.username, "password": password or recorder.password})
    try:
        host = validate_host(recorder.host)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if any(cam.use_case not in USE_CASES for cam in payload.cameras):
        raise HTTPException(422, "Unknown use case")
    if len({cam.channel_no for cam in payload.cameras}) != len(payload.cameras):
        raise HTTPException(422, "Duplicate channel in request")
    try:
        path_template = _template(recorder.template_key, recorder.custom_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    cipher = _cipher()
    with database() as conn:
        _one(conn, "SELECT id FROM branches WHERE id=?", (recorder.branch_id,))
        rec_id = str(uuid.uuid4())
        encrypted = cipher.encrypt(recorder.password.encode()).decode() if recorder.password else ""
        conn.execute("INSERT INTO recorders(id,branch_id,mode,host,rtsp_port,scheme,username,password_encrypted,path_template,stream,transport) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (rec_id, recorder.branch_id, recorder.mode, host, recorder.rtsp_port, recorder.scheme, recorder.username,
                      encrypted, path_template, recorder.stream, recorder.transport))
        result = []
        try:
            for cam in payload.cameras:
                ident = str(uuid.uuid4())
                code = f"CH-{cam.channel_no:02d}"
                conn.execute("INSERT INTO cameras(id,branch_id,recorder_id,channel_no,code,name,width,height,codec,fps) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (ident, recorder.branch_id, rec_id, cam.channel_no, code, cam.name, cam.width, cam.height, cam.codec, cam.fps))
                conn.execute("INSERT INTO camera_use_cases(camera_id,use_case) VALUES(?,?)", (ident, cam.use_case))
                result.append({"id": ident, "branch_id": recorder.branch_id, "recorder_id": rec_id, "channel_no": cam.channel_no,
                               "code": code, "name": cam.name, "use_cases": [cam.use_case], "status": "offline"})
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "A channel code already exists in this branch") from exc
        return {"recorder": public_recorder(conn.execute("SELECT * FROM recorders WHERE id=?", (rec_id,)).fetchone()), "cameras": result}
