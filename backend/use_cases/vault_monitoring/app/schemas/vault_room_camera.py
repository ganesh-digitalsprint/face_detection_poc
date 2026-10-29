"""API schemas for browser-controlled Vault Room camera sessions."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class VaultRoomCameraStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["webcam", "rtsp"]
    name: str = Field(default="Vault Room Camera", min_length=1, max_length=80)
    camera_index: int | None = Field(default=None, ge=0)
    rtsp_url: SecretStr | None = None


class VaultRoomCameraSessionResponse(BaseModel):
    session_id: str
    name: str
    source_type: Literal["webcam", "rtsp"]
    camera_index: int | None = None
    status: Literal["connecting", "connected", "streaming", "reconnecting", "failed", "stopped"]
    error: str | None = None
    last_frame_at: float | None = None
    stream_url: str
