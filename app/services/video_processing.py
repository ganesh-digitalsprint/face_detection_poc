"""Uploaded-video processing through the shared face frame pipeline."""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.face_recognition import FaceRecognitionService, FrameResult

logger = get_logger(__name__)


class VideoProcessingError(RuntimeError):
    """Uploaded video could not be decoded or annotated."""


def annotate_frame(frame: np.ndarray, result: FrameResult) -> np.ndarray:
    """Draw each face box, temporary track ID, and recognized/unknown name."""
    for face in result.faces:
        box = face.bbox
        x1, y1 = int(box.x), int(box.y)
        x2, y2 = x1 + int(box.width), y1 + int(box.height)
        color = (0, 190, 0) if face.matched else (0, 0, 230)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        name = face.name if face.matched and face.name else "Unknown"
        label = f"{name} | Track {face.track_id}"
        cv2.putText(
            frame, label, (x1, max(y1 - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX,
            0.55, color, 2, cv2.LINE_AA,
        )
    return frame


def process_video_file(
    source_path: Path,
    recognition: FaceRecognitionService,
    *,
    capture_factory=cv2.VideoCapture,
    writer_factory=cv2.VideoWriter,
) -> tuple[Path, int]:
    """Process an uploaded video, releasing capture/writer on every exit path."""
    settings.VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = settings.VIDEO_OUTPUT_DIR / f"recognized_{uuid.uuid4().hex}.mp4"
    capture = capture_factory(str(source_path))
    writer = None
    frame_number = 0
    completed = False
    try:
        if not capture.isOpened():
            raise VideoProcessingError("Uploaded file is not a readable video.")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps <= 0:
            fps = 25.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            raise VideoProcessingError("Video has invalid frame dimensions.")
        recognition.set_tracker_frame_rate(fps)
        codec = cv2.VideoWriter_fourcc(*"mp4v")
        writer = writer_factory(str(output_path), codec, fps, (width, height))
        if not writer.isOpened():
            raise VideoProcessingError("Could not create the annotated output video.")

        while True:
            ok, frame = capture.read()
            if not ok:
                break
            result = recognition.process_frame(frame, frame_number)
            writer.write(annotate_frame(frame, result))
            frame_number += 1
        if frame_number == 0:
            raise VideoProcessingError("Video contains no readable frames.")
        completed = True
        return output_path, frame_number
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if not completed:
            output_path.unlink(missing_ok=True)
        source_path.unlink(missing_ok=True)
