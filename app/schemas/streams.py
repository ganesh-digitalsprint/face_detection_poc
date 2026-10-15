"""Request/response schemas for live video sources."""

from pydantic import BaseModel, Field


class CCTVStartRequest(BaseModel):
    stream_index: int = Field(ge=0, description="Index in the configured RTSP_URLS list")


class CCTVCamera(BaseModel):
    """A configured CCTV source. Never carries the RTSP URL or credentials."""

    stream_index: int
    label: str


class StreamStartedResponse(BaseModel):
    session_id: str
    stream_url: str
    stop_url: str
