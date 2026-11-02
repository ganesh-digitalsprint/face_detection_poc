"""Liveness Test Lab API: developer diagnostics, never a vault decision.

Mounted only when ``LIVENESS_TEST_ENABLED`` is true; every route also re-checks the flag
and answers 404 when it is off. No database, Qdrant or employee data is used here.
"""

from __future__ import annotations

import threading
import time
from typing import Annotated

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.api.dependencies import read_upload_bytes
from app.api.errors import ErrorResponse
from app.core.config import settings
from app.core.liveness_config import get_liveness_test_config
from app.schemas.liveness_test import (
    LivenessTestAnalysis,
    TestAck,
    TestChallengeRequest,
    TestConfigResponse,
    TestSessionStarted,
)
from app.services.liveness_test_service import (
    MEDIAPIPE,
    InvalidTestRequestError,
    LivenessTestService,
    LivenessTestSessionNotFoundError,
    get_liveness_test_service,
)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def require_enabled() -> None:
    # The app has no user roles; this flag is the access control for the developer tool.
    if not settings.LIVENESS_TEST_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


class TokenBucketLimiter:
    """Small in-process per-client token bucket (no limiter exists in the project)."""

    def __init__(self, rate_per_second: float, burst: float | None = None, max_clients: int = 1024) -> None:
        self._rate = rate_per_second
        self._burst = burst or rate_per_second
        self._max_clients = max_clients
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, updated = self._buckets.get(key, (self._burst, now))
            tokens = min(self._burst, tokens + (now - updated) * self._rate)
            allowed = tokens >= 1.0
            self._buckets[key] = (tokens - 1.0 if allowed else tokens, now)
            if len(self._buckets) > self._max_clients:  # bound memory: drop the stalest client
                self._buckets.pop(min(self._buckets, key=lambda k: self._buckets[k][1]), None)
            return allowed


_limiter = TokenBucketLimiter(get_liveness_test_config().rate_limit_per_second)


def rate_limited(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(client):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many frames; slow down")


router = APIRouter(
    prefix="/api/v1/liveness-test",
    tags=["liveness test"],
    dependencies=[Depends(require_enabled)],
    responses={404: {"model": ErrorResponse, "description": "Feature disabled or session not found"}},
)
Service = Annotated[LivenessTestService, Depends(get_liveness_test_service)]


def _not_found(exc: LivenessTestSessionNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _decode_frame(frame: UploadFile) -> np.ndarray:
    if frame.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Unsupported image type; use JPEG, PNG, or WebP")
    data = read_upload_bytes(frame, limit=get_liveness_test_config().max_upload_bytes)
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")
    return image


@router.get("/config", response_model=TestConfigResponse)
def get_config(service: Service) -> TestConfigResponse:
    """Thresholds the lab uses (shared with production) and which detectors can run."""
    return TestConfigResponse(thresholds=service.thresholds(), detectors=service.detector_availability())


@router.post("/sessions", response_model=TestSessionStarted, status_code=status.HTTP_201_CREATED)
def start_session(service: Service) -> TestSessionStarted:
    return TestSessionStarted(session_id=service.start_session(), thresholds=service.thresholds())


@router.post(
    "/sessions/{session_id}/analyze",
    response_model=LivenessTestAnalysis,
    dependencies=[Depends(rate_limited)],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image, detector or challenge"},
        413: {"model": ErrorResponse, "description": "Frame larger than 2 MB"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
def analyze_frame(
    session_id: str,
    service: Service,
    frame: Annotated[UploadFile, File(description="Camera frame (JPEG, PNG or WebP, max 2 MB)")],
    detector: Annotated[str, Form()] = MEDIAPIPE,
    challenge: Annotated[str | None, Form()] = None,
) -> LivenessTestAnalysis:
    """Sync handler: FastAPI runs it in the threadpool, so detection never blocks the event loop."""
    image = _decode_frame(frame)
    try:
        return service.analyze(session_id, image, detector=detector, challenge=challenge)
    except LivenessTestSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidTestRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/reset", response_model=TestAck)
def reset_baseline(session_id: str, service: Service) -> TestAck:
    try:
        service.reset_baseline(session_id)
    except LivenessTestSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    return TestAck(session_id_prefix=session_id[:8])


@router.post("/sessions/{session_id}/challenge", response_model=TestAck)
def set_challenge(session_id: str, body: TestChallengeRequest, service: Service) -> TestAck:
    try:
        service.set_challenge(session_id, body.challenge)
    except LivenessTestSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidTestRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TestAck(session_id_prefix=session_id[:8])


@router.delete("/sessions/{session_id}", response_model=TestAck)
def end_session(session_id: str, service: Service) -> TestAck:
    try:
        service.end_session(session_id)
    except LivenessTestSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    return TestAck(session_id_prefix=session_id[:8])
