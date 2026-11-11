from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

CameraType = Literal["rtsp", "webcam", "upload", "folder"]
MASK = "********"
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^/\s@]*@")


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cam_type: CameraType
    source: str = Field(min_length=1, max_length=500)
    username: str = ""
    password: str = ""
    location: str = ""
    enabled: bool = True
    loop_video: bool = False


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    source: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = None
    password: str | None = None
    location: str | None = None
    enabled: bool | None = None
    loop_video: bool | None = None


class Camera(CameraCreate):
    """Internal shape: includes the real password. Never return this from an API; use `public()`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: UtcDatetime

    def public(self) -> "CameraPublic":
        """FM-13: password never leaves the service; username and URL-embedded credentials are masked too."""
        return CameraPublic(
            id=self.id,
            name=self.name,
            cam_type=self.cam_type,
            source=_URL_CREDENTIALS.sub(r"\g<scheme>***:***@", self.source),
            username=MASK if self.username else "",
            has_password=bool(self.password),
            location=self.location,
            enabled=self.enabled,
            loop_video=self.loop_video,
            created_at=self.created_at,
        )


class CameraPublic(BaseModel):
    id: str
    name: str
    cam_type: CameraType
    source: str
    username: str
    has_password: bool
    location: str
    enabled: bool
    loop_video: bool
    created_at: UtcDatetime
