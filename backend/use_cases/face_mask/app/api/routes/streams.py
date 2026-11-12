"""Live annotated stream (MJPEG over HTTP, the same mechanism as branch_exterior) and an unannotated still frame."""
from __future__ import annotations

import asyncio

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runtime, get_session
from app.core.exceptions import NotFoundError
from app.db.repositories.sql_repo import CameraRepository
from app.services.runtime import Runtime
from app.services.sources import FILE_TYPES, open_capture

router = APIRouter(prefix="/streams", tags=["streams"])

_BOUNDARY = "frame"
_POLL_SECONDS = 0.08


async def _mjpeg(request: Request, runtime: Runtime, camera_id: str, debug: bool = False):
    last: bytes | None = None
    while not await request.is_disconnected():
        jpeg = runtime.bus.latest_jpeg(camera_id, debug=debug)
        if jpeg is not None and jpeg is not last:
            last = jpeg
            yield (b"--" + _BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
        await asyncio.sleep(_POLL_SECONDS)


@router.get("/{camera_id}/processed")
async def processed_stream(camera_id: str, request: Request, debug: bool = False, runtime: Runtime = Depends(get_runtime)):
    """Annotated MJPEG: person box, Track ID, ROI, head box, score, state. 404 until the camera has produced a frame."""
    if runtime.bus.latest_jpeg(camera_id, debug=debug) is None:
        raise HTTPException(404, "This camera is not running (start it first)")
    return StreamingResponse(_mjpeg(request, runtime, camera_id, debug),
                             media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}")


@router.get("/{camera_id}/snapshot")
async def snapshot(camera_id: str, pos: float = 0.0, session: AsyncSession = Depends(get_session)):
    """One unannotated frame, used to draw the entry ROI. For video files `pos` (0..1) seeks within the file."""
    camera = await CameraRepository(session).get(camera_id)
    if camera is None:
        raise NotFoundError(f"Camera {camera_id} not found")

    def grab() -> bytes | None:
        cap = open_capture(camera)
        if cap is None:
            return None
        try:
            if camera.cam_type in FILE_TYPES and pos > 0:
                total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(total - 1, int(total * min(max(pos, 0.0), 1.0)))))
            ok, frame = cap.read()
            if not ok:
                return None
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return encoded.tobytes() if ok else None
        finally:
            cap.release()

    jpeg = await asyncio.to_thread(grab)
    if jpeg is None:
        raise HTTPException(502, "Could not read a frame from this camera")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
