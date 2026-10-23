"""Request/response schemas for live video sources."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class CCTVStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream_index: int | None = Field(default=None, ge=0, description="Index in configured RTSP_URLS")
    rtsp_url: SecretStr | None = Field(default=None, description="A validated RTSP/RTSPS source URL")


class CCTVCamera(BaseModel):
    """A configured CCTV source. Never carries the RTSP URL or credentials."""

    stream_index: int
    label: str


class StreamStartedResponse(BaseModel):
    session_id: str
    stream_url: str
    stop_url: str
