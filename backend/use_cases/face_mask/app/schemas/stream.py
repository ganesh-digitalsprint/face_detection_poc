from __future__ import annotations

from pydantic import BaseModel

from app.schemas.camera import CameraPublic
from app.services.frame_bus import CameraStatus


class StreamStatus(BaseModel):
    camera_id: str
    status: str            # ONLINE | RECONNECTING | OFFLINE | PROCESSING | DONE | STOPPED | ERROR
    running: bool
    fps: float
    frames_read: int
    frames_total: int
    native_fps: float = 0.0
    position_seconds: float = 0.0
    total_seconds: float = 0.0
    can_resume: bool = False
    resume_mode: str = ""
    percent: float
    events_found: int
    last_error: str
    notice: str
    active_tracks: int
    track_states: dict[int, str]

    @classmethod
    def of(cls, status: CameraStatus) -> "StreamStatus":
        return cls(camera_id=status.camera_id, status=status.status, running=status.running, fps=status.fps,
                   frames_read=status.frames_read, frames_total=status.frames_total, native_fps=status.native_fps, percent=status.percent,
                   position_seconds=status.position_seconds, total_seconds=status.total_seconds,
                   can_resume=status.can_resume, resume_mode=status.resume_mode,
                   events_found=status.events_found, last_error=status.last_error, notice=status.notice,
                   active_tracks=status.active_tracks, track_states=dict(status.track_states))


class CameraView(CameraPublic):
    """Camera (credentials masked) plus its live status."""
    stream: StreamStatus


class CamerasOnline(BaseModel):
    cameras_online: int
    cameras_total: int
