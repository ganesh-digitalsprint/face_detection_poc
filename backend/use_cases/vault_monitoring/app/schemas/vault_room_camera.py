"""API schemas for browser-controlled Vault Room camera sessions."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class VaultRoomCameraStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["webcam", "rtsp"]
    name: str = Field(default="Vault Room Camera", min_length=1, max_length=80)
    camera_index: int | None = Field(default=None, ge=0)
    rtsp_url: SecretStr | None = None
    pose_preview: bool = False
    branch_id: str | None = Field(default=None, min_length=1, max_length=128)


class VaultRoomCameraSessionResponse(BaseModel):
    session_id: str
    name: str
    source_type: Literal["webcam", "rtsp"]
    camera_index: int | None = None
    status: Literal["connecting", "connected", "streaming", "reconnecting", "failed", "stopped"]
    error: str | None = None
    last_frame_at: float | None = None
    pose_preview: bool = False
    pose_metrics: dict | None = None
    stream_url: str
    source_context: dict = Field(default_factory=dict)


class VaultBrowserSourceStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Vault Room Camera", min_length=1, max_length=80)
    branch_id: str | None = Field(default=None, min_length=1, max_length=128)


class VaultBrowserSourceResponse(BaseModel):
    session_id: str
    name: str
    source_type: Literal["browser_webcam"] = "browser_webcam"
    source_context: dict = Field(default_factory=dict)
