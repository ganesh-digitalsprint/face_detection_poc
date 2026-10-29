"""Direct webcam and RTSP ingestion for Vault Room's person-counting pipeline."""
from __future__ import annotations

import ipaddress
import queue
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

import cv2

from app.core.config import settings
from app.core.logging import get_logger
from app.core.ml_config import get_vault_room_config
from app.services.vault_room_manager import VaultRoomBusyError, VaultRoomDetectorUnavailableError
from app.services.camera_capture import open_webcam_capture

logger = get_logger(__name__)


def _is_private_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_private and not (address.is_loopback or address.is_link_local
        or address.is_multicast or address.is_unspecified or address.is_reserved)


def validate_rtsp_url(url: str, *, allowed_hosts: list[str] | None = None) -> str:
    """Validate URL syntax without ever returning it in an error message."""
    try:
        parsed = urlsplit(url.strip())
        valid = (parsed.scheme.lower() in {"rtsp", "rtsps"} and bool(parsed.hostname)
                 and not any(ch.isspace() for ch in url) and len(url) <= 2048)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            valid = False
        if valid:
            host = parsed.hostname.rstrip(".").lower()
            configured = settings.RTSP_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
            if configured:
                rules = [item.strip().lower().lstrip(".").rstrip(".") for item in configured if item.strip()]
                valid = any(host == rule or host.endswith("." + rule) for rule in rules)
            else:
                try:
                    addresses = [host]
                    try:
                        ipaddress.ip_address(host)
                    except ValueError:
                        addresses = list({entry[4][0] for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
                    valid = bool(addresses) and all(_is_private_address(item) for item in addresses)
                except (OSError, ValueError):
                    valid = False
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise ValueError("Enter a valid rtsp:// or rtsps:// stream URL.")
    return url.strip()


@dataclass
class VaultRoomCameraSession:
    session_id: str
    name: str
    url: str = field(repr=False)
    source_type: str = "rtsp"
    camera_index: int | None = None
    status: str = "connecting"
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_client_seen: float = field(default_factory=time.monotonic)
    last_frame_at: float | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    capture_done: threading.Event = field(default_factory=threading.Event)
    capture_lock: threading.Lock = field(default_factory=threading.Lock)
    raw_frames: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    frames: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    capture: object | None = None
    capture_thread: threading.Thread | None = None
    thread: threading.Thread | None = None
    fps: float = field(default_factory=lambda: max(0.5, min(5.0, float(
        get_vault_room_config().counting.recommended_fps))))


class VaultRoomCameraManager:
    def __init__(self, *, capture_factory: Callable = cv2.VideoCapture, room_manager=None):
        self._capture_factory = capture_factory
        self._room_manager = room_manager
        self._lock = threading.RLock()
        self._session: VaultRoomCameraSession | None = None
        self._stopped_ids: deque[str] = deque(maxlen=128)

    def start_rtsp(self, name: str, url: str) -> VaultRoomCameraSession:
        url = validate_rtsp_url(url)
        return self._start("rtsp", name, url)

    def start_webcam(self, name: str, camera_index: int | None = None) -> VaultRoomCameraSession:
        index = settings.WEBCAM_INDEX if camera_index is None else camera_index
        if index < 0:
            raise ValueError("Camera index must be zero or greater.")
        return self._start("webcam", name, "", camera_index=int(index))

    def _start(self, source_type: str, name: str, url: str, *, camera_index: int | None = None) -> VaultRoomCameraSession:
        with self._lock:
            if self._session and self._session.status not in {"failed", "stopped"}:
                raise RuntimeError("A Vault Room camera is already connected. Disconnect it before starting another.")
            session = VaultRoomCameraSession(uuid.uuid4().hex, name.strip()[:80] or "Vault Room Camera", url,
                source_type=source_type, camera_index=camera_index)
            self._session = session
            session.thread = threading.Thread(target=self._run, args=(session,),
                name=f"vault-room-camera-{session.session_id[:8]}", daemon=True)
            session.thread.start()
            return session

    def get(self, session_id: str) -> VaultRoomCameraSession | None:
        with self._lock:
            return self._session if self._session and self._session.session_id == session_id else None

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._session and self._session.status not in {"failed", "stopped"})

    def stop(self, session_id: str) -> bool:
        session = self.get(session_id)
        if session is None:
            return session_id in self._stopped_ids
        session.stop_event.set()
        with session.capture_lock:
            capture = session.capture
        if capture is not None:
            capture.release()
        if session.thread:
            session.thread.join(timeout=max(settings.RTSP_READ_TIMEOUT_MS / 1000 + 2, 5))
        if session.capture_thread:
            session.capture_thread.join(timeout=max(settings.RTSP_READ_TIMEOUT_MS / 1000 + 2, 5))
        with self._lock:
            if self._session is session:
                session.status = "stopped"
                session.url = ""
                self._session = None
                self._stopped_ids.append(session_id)
        return True

    def stop_all(self) -> None:
        with self._lock:
            session_id = self._session.session_id if self._session else None
        if session_id:
            self.stop(session_id)

    def status(self, session: VaultRoomCameraSession) -> dict:
        session.last_client_seen = time.monotonic()
        return {"session_id": session.session_id, "name": session.name, "source_type": session.source_type,
                "camera_index": session.camera_index,
                "status": session.status, "error": session.error,
                "last_frame_at": session.last_frame_at}

    def stream(self, session_id: str):
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        while not session.stop_event.is_set() or not session.frames.empty():
            try:
                frame = session.frames.get(timeout=1)
            except queue.Empty:
                if session.status == "failed":
                    break
                continue
            if frame is None:
                break
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    @staticmethod
    def _offer_latest(session: VaultRoomCameraSession, data, *, raw: bool = False) -> None:
        target = session.raw_frames if raw else session.frames
        try:
            target.put_nowait(data)
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            try:
                target.put_nowait(data)
            except queue.Full:
                pass

    def _run(self, session: VaultRoomCameraSession) -> None:
        session.capture_thread = threading.Thread(target=self._capture_latest, args=(session,),
            name=f"vault-room-capture-{session.session_id[:8]}", daemon=True)
        session.capture_thread.start()
        try:
            manager = self._room_manager or __import__(
                "app.services.vault_room_manager", fromlist=["get_vault_room_manager"]
            ).get_vault_room_manager()
            process_interval = 1.0 / session.fps
            preview_interval = 0.1  # Keep the preview responsive even while counting runs at 5 FPS.
            last_process = -process_interval
            last_output = 0.0
            latest_tracks: list[dict] = []
            while not session.stop_event.is_set() or not session.raw_frames.empty():
                if time.monotonic() - session.last_client_seen > 30:
                    session.status = "stopped"
                    session.stop_event.set()
                    break
                delay = preview_interval - (time.monotonic() - last_output)
                if last_output and delay > 0 and session.stop_event.wait(delay):
                    break
                try:
                    frame = session.raw_frames.get(timeout=0.5)
                except queue.Empty:
                    if session.capture_done.is_set():
                        break
                    continue
                if frame is None:
                    break
                now = time.monotonic()
                if now - last_process >= process_interval:
                    try:
                        result = manager.process_frame(frame, source=session.source_type)
                    except VaultRoomBusyError:
                        pass  # Drop this count sample; capture continues with only the newest frame.
                    except VaultRoomDetectorUnavailableError as exc:
                        session.status = "failed"
                        session.error = str(exc)
                        break
                    except Exception:
                        session.status = "failed"
                        session.error = "Vault Room frame processing failed."
                        logger.exception("Vault Room camera processing failed session=%s", session.session_id[:8])
                        break
                    else:
                        last_process = time.monotonic()
                        if result.get("accepts_frames", True):
                            latest_tracks = result.get("tracks", [])
                            session.status = "streaming"
                            session.error = None
                        else:
                            latest_tracks = []
                            if session.status not in {"reconnecting", "failed", "stopped"}:
                                session.status = "connected"
                    # Inference may take longer than one preview tick; discard its stale input.
                    try:
                        newest = session.raw_frames.get_nowait()
                        if newest is not None:
                            frame = newest
                    except queue.Empty:
                        pass
                frame = self._annotate(frame, latest_tracks)
                height, width = frame.shape[:2]
                if width > 960:
                    preview_height = max(1, round(height * 960 / width))
                    frame = cv2.resize(frame, (960, preview_height), interpolation=cv2.INTER_AREA)
                encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if encoded:
                    self._offer_latest(session, buffer.tobytes())
                session.last_frame_at = time.time()
                last_output = time.monotonic()
        except Exception:
            session.status = "failed"
            session.error = (f"The webcam capture failed at index {session.camera_index}. Check that it is connected and available."
                if session.source_type == "webcam" else
                "The RTSP camera connection failed. Check the URL, allowed host, network, and camera credentials.")
            # Never log the source URI: it may contain credentials.
            logger.warning("Vault Room camera failed source=%s session=%s", session.source_type, session.session_id[:8])
        finally:
            session.stop_event.set()
            if session.capture_thread and session.capture_thread.is_alive():
                with session.capture_lock:
                    capture = session.capture
                if capture is not None:
                    capture.release()
                session.capture_thread.join(timeout=max(settings.RTSP_READ_TIMEOUT_MS / 1000 + 2, 5))
            self._offer_latest(session, None)

    def _capture_latest(self, session: VaultRoomCameraSession) -> None:
        capture = None
        reconnects = 0
        try:
            while not session.stop_event.is_set():
                capture = self._open_capture(session)
                with session.capture_lock:
                    if session.stop_event.is_set():
                        capture.release()
                        break
                    session.capture = capture
                if not capture.isOpened():
                    capture.release()
                    if reconnects >= settings.RTSP_RECONNECT_ATTEMPTS:
                        source = "webcam" if session.source_type == "webcam" else "RTSP camera"
                        raise RuntimeError(f"Could not connect to the {source}. Check the camera and connection.")
                    reconnects += 1
                    session.status = "reconnecting"
                    if session.stop_event.wait(settings.RTSP_RECONNECT_DELAY_SECONDS):
                        break
                    continue
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                session.status = "connected"
                while not session.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        reconnects += 1
                        if reconnects > settings.RTSP_RECONNECT_ATTEMPTS:
                            source = "webcam" if session.source_type == "webcam" else "RTSP camera"
                            raise RuntimeError(f"The {source} stopped sending frames. Check the camera and connection.")
                        session.status = "reconnecting"
                        break
                    reconnects = 0
                    self._offer_latest(session, frame, raw=True)
                capture.release()
                with session.capture_lock:
                    if session.capture is capture:
                        session.capture = None
                if session.stop_event.is_set():
                    break
                if session.stop_event.wait(settings.RTSP_RECONNECT_DELAY_SECONDS):
                    break
        except Exception:
            session.status = "failed"
            session.error = (f"The webcam capture failed at index {session.camera_index}. Check that it is connected and available."
                if session.source_type == "webcam" else
                "The RTSP camera connection failed. Check the URL, allowed host, network, and camera credentials.")
            logger.warning("Vault Room camera capture failed source=%s session=%s", session.source_type, session.session_id[:8])
        finally:
            if capture is not None:
                capture.release()
            with session.capture_lock:
                session.capture = None
            session.capture_done.set()
            self._offer_latest(session, None, raw=True)

    def _open_capture(self, session: VaultRoomCameraSession):
        if session.source_type == "webcam":
            return open_webcam_capture(session.camera_index, capture_factory=self._capture_factory)
        return self._capture_factory(session.url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, settings.RTSP_READ_TIMEOUT_MS,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, settings.RTSP_READ_TIMEOUT_MS,
        ])

    @staticmethod
    def _annotate(frame, tracks):
        height, width = frame.shape[:2]
        for track in tracks:
            x1 = int(track["x"] * width)
            y1 = int(track["y"] * height)
            x2 = int((track["x"] + track["w"]) * width)
            y2 = int((track["y"] + track["h"]) * height)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 190, 0), 2)
            cv2.putText(frame, f"Person {track['track_id']}", (x1, max(y1 - 8, 18)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 190, 0), 2)
        return frame


_manager = VaultRoomCameraManager()


def get_vault_room_camera_manager() -> VaultRoomCameraManager:
    return _manager
