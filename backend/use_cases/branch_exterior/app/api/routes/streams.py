from __future__ import annotations

import asyncio

import cv2
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.services.frame_bus import frame_bus

router = APIRouter(prefix="/streams", tags=["streams"])

_BOUNDARY = "frame"


async def _mjpeg_generator(camera_id: str, processed: bool):
    while True:
        state = frame_bus.get(camera_id)
        if state is None:
            return
        if not state.running and state.status in ("FINISHED", "STOPPED", "ERROR"):
            return
        frame = state.get_processed() if processed else state.get_raw()
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            yield (
                b"--" + _BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
        await asyncio.sleep(1 / 12)  # cap the stream at ~12 FPS regardless of processing rate


@router.get("/{camera_id}/last")
async def last_frame(camera_id: str):
    state = frame_bus.get(camera_id)
    if state is None or state.frame_count == 0:
        raise HTTPException(404, "No frame has been processed")
    ok, buf = cv2.imencode(".jpg", state.get_processed(), [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise HTTPException(500, "Could not encode frame")
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{camera_id}/raw")
async def stream_raw(camera_id: str):
    if frame_bus.get(camera_id) is None:
        raise HTTPException(404, "Camera is not running - start it first")
    return StreamingResponse(
        _mjpeg_generator(camera_id, processed=False),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
    )


@router.get("/{camera_id}/processed")
async def stream_processed(camera_id: str):
    if frame_bus.get(camera_id) is None:
        raise HTTPException(404, "Camera is not running - start it first")
    return StreamingResponse(
        _mjpeg_generator(camera_id, processed=True),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
    )
