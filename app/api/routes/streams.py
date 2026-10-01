"""Webcam and configured CCTV stream endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.schemas.streams import CCTVStartRequest, StreamStartedResponse
from app.services.stream_manager import StreamManager, StreamOpenError

router = APIRouter(prefix="/api/v1/streams", tags=["streams"])
stream_manager = StreamManager()


@router.post("/webcam", response_model=StreamStartedResponse)
def start_webcam() -> StreamStartedResponse:
    """Start the configured local webcam and return its live stream URL."""
    try:
        session = stream_manager.start_webcam()
    except StreamOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamStartedResponse(
        session_id=session.session_id,
        stream_url=f"/api/v1/streams/{session.session_id}/stream",
        stop_url=f"/api/v1/streams/{session.session_id}/stop",
    )


@router.post("/cctv", response_model=StreamStartedResponse)
def start_cctv(request: CCTVStartRequest) -> StreamStartedResponse:
    """Start a configured RTSP source by its index; credentials stay in config."""
    urls = settings.RTSP_URLS
    if request.stream_index >= len(urls):
        raise HTTPException(status_code=404, detail="Configured RTSP stream index not found.")
    try:
        session = stream_manager.start_rtsp(urls[request.stream_index].get_secret_value())
    except StreamOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamStartedResponse(
        session_id=session.session_id,
        stream_url=f"/api/v1/streams/{session.session_id}/stream",
        stop_url=f"/api/v1/streams/{session.session_id}/stop",
    )


@router.get("/{session_id}/stream")
def stream_frames(session_id: str) -> StreamingResponse:
    """Stream annotated frames as MJPEG; client disconnect stops the session."""
    try:
        frames = stream_manager.stream(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Stream session not found.") from exc
    return StreamingResponse(frames, media_type="multipart/x-mixed-replace; boundary=frame")


@router.post("/{session_id}/stop")
def stop_stream(session_id: str) -> dict[str, str]:
    """Stop a webcam or RTSP session and release its capture and DB session."""
    if not stream_manager.stop(session_id):
        raise HTTPException(status_code=404, detail="Stream session not found.")
    return {"session_id": session_id, "status": "stopped"}
