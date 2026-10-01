"""Face recognition service: identification, verification and tracked video.

Pipeline (image, uploaded video and webcam frames share it):

    frame -> detection -> tracking -> track_id
          -> recognition due? -- no  -> reuse the track's identity
                              -- yes -> crop -> ArcFace -> Qdrant search
                                        -> distance -> threshold -> MATCH / Unknown

Key rules:
    * ``track_id`` is temporary, belongs to one ``FaceRecognitionService``
      instance (one video/session), and is never a person id.
    * Database recognition runs once per ``RECOGNITION_INTERVAL_FRAMES`` per
      track, not on every frame.
    * A failed recognition never invents an identity: the track keeps what it
      had (or stays Unknown).
    * ``distance`` (lower = more alike), ``similarity`` (``1 - distance``) and
      ``threshold`` (maximum distance for a match) are never probabilities.

Threading: an instance holds tracker state for ONE video/session and must be
used from one thread at a time. Use a dedicated read-only ``Session``; it is
rolled back after each search so no connection sits idle in a transaction.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import supervision as sv
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.repositories import (
    EmbeddingMatch,
    FaceEmbeddingRepository,
    PersonRepository,
    RepositoryError,
)
from app.ml.deepface_service import FaceDetectionError, FaceProcessingError
from app.schemas.face import BoundingBox as BoundingBoxSchema
from app.schemas.recognition import (
    RecognitionResponse,
    RecognitionResult,
    VerificationResponse,
)
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.services.face_embedding import FaceEmbeddingService, get_face_embedding_service
from app.utils.image import BoundingBox, Image, InvalidImageError, validate_image
from app.utils.similarity import is_match

logger = get_logger(__name__)


class PersonNotFoundError(LookupError):
    """No person exists with the given person_code."""


class NoEnrolledEmbeddingError(LookupError):
    """The person has no active embeddings for the current model."""


# ----------------------------------------------------------------------
# Recognition outcome
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecognitionOutcome:
    """Result of comparing one face against the database.

    For an unknown face the identity fields are None, but ``distance`` and
    ``similarity`` still describe the nearest stored embedding (None only when
    the database has no candidate).
    """

    matched: bool
    person_id: int | None = None
    person_code: str | None = None
    name: str | None = None
    distance: float | None = None
    similarity: float | None = None

    @classmethod
    def from_match(cls, match: EmbeddingMatch | None, threshold: float) -> RecognitionOutcome:
        """Apply the configured threshold to the nearest database match."""
        if match is None:
            return cls(matched=False)
        distance = min(max(match.distance, 0.0), 2.0)  # guard float noise
        similarity = 1.0 - distance
        if is_match(distance, threshold):
            return cls(
                matched=True,
                person_id=match.person_id,
                person_code=match.person_code,
                name=match.name,
                distance=distance,
                similarity=similarity,
            )
        return cls(matched=False, distance=distance, similarity=similarity)


# ----------------------------------------------------------------------
# Tracking
# ----------------------------------------------------------------------
@dataclass(slots=True)
class Track:
    """One tracked face. ``track_id`` is temporary and is not a person id."""

    track_id: int
    bbox: BoundingBox
    last_seen_frame: int
    consecutive_missed_frames: int = 0
    last_recognition_frame: int | None = None
    matched: bool = False
    person_id: int | None = None
    person_code: str | None = None
    name: str | None = None
    distance: float | None = None
    similarity: float | None = None
    last_outcome: RecognitionOutcome | None = None
    # Contradicting-result hysteresis (see record_recognition).
    _pending_key: int | None = field(default=None, repr=False)
    _pending_count: int = field(default=0, repr=False)

    @property
    def identity(self) -> str:
        """Display identity: the person's name, or ``"Unknown"``."""
        return self.name if self.matched and self.name else "Unknown"

    def recognition_due(self, frame_number: int, interval: int) -> bool:
        """True for a never-recognized track, or once ``interval`` frames passed."""
        if self.last_recognition_frame is None:
            return True
        return frame_number - self.last_recognition_frame >= interval

    def record_recognition(
        self, outcome: RecognitionOutcome | None, frame_number: int, confirmations: int
    ) -> None:
        """Fold a recognition attempt into the track.

        * ``None`` (the attempt failed): nothing changes except the attempt is
          counted, so a failing face is not retried on every frame.
        * Unknown track: any result is adopted immediately.
        * Known track, same person: refresh distance/similarity.
        * Known track, contradicting result (other person, or Unknown): adopted
          only after ``confirmations`` consecutive contradicting results.
        """
        self.last_recognition_frame = frame_number
        self.last_outcome = outcome
        if outcome is None:
            return

        if not self.matched or (outcome.matched and outcome.person_id == self.person_id):
            self._adopt(outcome)
            return

        key = outcome.person_id if outcome.matched else None
        if self._pending_count > 0 and self._pending_key == key:
            self._pending_count += 1
        else:
            self._pending_key, self._pending_count = key, 1
        if self._pending_count >= confirmations:
            self._adopt(outcome)

    def _adopt(self, outcome: RecognitionOutcome) -> None:
        self.matched = outcome.matched
        self.person_id = outcome.person_id
        self.person_code = outcome.person_code
        self.name = outcome.name
        self.distance = outcome.distance
        self.similarity = outcome.similarity
        self._pending_key, self._pending_count = None, 0


class FaceTracker:
    """Session-local ByteTrack association plus recognition state per track."""

    def __init__(self, iou_threshold: float, max_missed_frames: int, frame_rate: float) -> None:
        self._iou_threshold = iou_threshold
        self._max_missed = max_missed_frames
        self._tracks: list[Track] = []
        self._byte_track = sv.ByteTrack(
            track_activation_threshold=0.05,
            lost_track_buffer=max(1, round(max_missed_frames * 30 / max(frame_rate, 1.0))),
            minimum_matching_threshold=iou_threshold,
            frame_rate=max(frame_rate, 1.0),
            minimum_consecutive_frames=1,
        )

    @property
    def active_tracks(self) -> list[Track]:
        """All live tracks, including ones not seen in the latest frame."""
        return list(self._tracks)

    def update(
        self, boxes: Sequence[BoundingBox], frame_number: int,
        confidences: Sequence[float | None] | None = None,
    ) -> list[Track]:
        """Associate detections with ByteTrack; return visible tracks in input order."""
        xyxy = np.asarray([box.to_xyxy() for box in boxes], dtype=np.float32).reshape(-1, 4)
        confidence_values = confidences if confidences is not None else [None] * len(boxes)
        scores = np.asarray([
            1.0 if confidences is None or confidence is None else confidence
            for confidence in confidence_values
        ], dtype=np.float32)
        detections = sv.Detections(xyxy=xyxy, confidence=scores)
        tracked = self._byte_track.update_with_detections(detections)
        tracker_ids = tracked.tracker_id
        if tracker_ids is None:
            tracker_ids = np.full(len(boxes), -1, dtype=np.int64)

        by_id = {track.track_id: track for track in self._tracks}
        visible: list[Track] = []
        seen_ids: set[int] = set()
        # Supervision filters out detections that have not yet been activated,
        # so its result can be shorter than the input. Use its returned boxes
        # alongside IDs instead of zipping IDs to the unfiltered detections.
        for coordinates, raw_id in zip(tracked.xyxy, tracker_ids, strict=False):
            track_id = int(raw_id)
            if track_id < 0:
                continue
            x1, y1, x2, y2 = (int(round(value)) for value in coordinates)
            box = BoundingBox(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
            track = by_id.get(track_id)
            if track is None:
                track = Track(track_id=track_id, bbox=box, last_seen_frame=frame_number)
                self._tracks.append(track)
                by_id[track_id] = track
                logger.debug("ByteTrack created track %s at frame %s", track_id, frame_number)
            track.bbox = box
            track.last_seen_frame = frame_number
            track.consecutive_missed_frames = 0
            visible.append(track)
            seen_ids.add(track_id)

        for track in self._tracks:
            if track.track_id not in seen_ids:
                track.consecutive_missed_frames += 1
        kept = [t for t in self._tracks if t.consecutive_missed_frames < self._max_missed]
        for track in self._tracks:
            if track.consecutive_missed_frames >= self._max_missed:
                logger.debug("Removed stale track %s", track.track_id)
        self._tracks = kept
        return visible


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FrameResult:
    """Recognition results for one processed frame."""

    frame_number: int
    faces: list[RecognitionResult]
    processing_time_ms: float


class FaceRecognitionService:
    """Identification, verification and tracked recognition of video frames."""

    def __init__(
        self,
        session: Session,
        detection: FaceDetectionService | None = None,
        embedding: FaceEmbeddingService | None = None,
        *,
        person_repository: PersonRepository | None = None,
        embedding_repository: FaceEmbeddingRepository | None = None,
        recognition_interval_frames: int | None = None,
        iou_threshold: float | None = None,
        max_missed_frames: int | None = None,
        identity_change_confirmations: int | None = None,
        tracker_frame_rate: float = 30.0,
    ) -> None:
        self._session = session
        self._detection = detection or get_face_detection_service()
        self._embedding = embedding or get_face_embedding_service()
        self._persons = person_repository or PersonRepository(session)
        self._embeddings = embedding_repository or FaceEmbeddingRepository(session)

        self._config = self._embedding.model_config
        if self._config.distance_metric != "cosine":
            raise ValueError(
                "Database search is implemented for cosine distance only "
                f"(FACE_DISTANCE_METRIC={self._config.distance_metric!r})"
            )

        self._interval = recognition_interval_frames or settings.RECOGNITION_INTERVAL_FRAMES
        self._confirmations = (
            identity_change_confirmations or settings.TRACK_IDENTITY_CHANGE_CONFIRMATIONS
        )
        self._iou_threshold = iou_threshold or settings.TRACK_IOU_THRESHOLD
        self._max_missed = max_missed_frames or settings.MAX_TRACK_MISSED_FRAMES
        self._tracker_frame_rate = tracker_frame_rate
        self._tracker = FaceTracker(self._iou_threshold, self._max_missed, tracker_frame_rate)

    # -- session lifecycle -------------------------------------------------
    def reset(self) -> None:
        """Start a new video/session: clears all tracks; ids restart at 1."""
        self._tracker = FaceTracker(self._iou_threshold, self._max_missed, self._tracker_frame_rate)

    def set_tracker_frame_rate(self, frame_rate: float) -> None:
        """Set source FPS before processing begins; lost-track timeout stays frame based."""
        self._tracker_frame_rate = max(float(frame_rate), 1.0)
        self._tracker = FaceTracker(
            self._iou_threshold, self._max_missed, self._tracker_frame_rate
        )

    @property
    def active_tracks(self) -> list[Track]:
        """Currently live tracks (for diagnostics and tests)."""
        return self._tracker.active_tracks

    # -- single image ---------------------------------------------------------
    def identify_image(self, image: Image) -> RecognitionResponse:
        """Identify every face in one image (no tracking; ``track_id`` is null).

        A face whose embedding cannot be computed is returned as Unknown.

        Raises:
            InvalidImageError, FaceDetectionError, RepositoryError.
        """
        started = time.perf_counter()
        validate_image(image)
        faces = self._detection.detect(image, max_side=settings.VIDEO_MAX_FRAME_SIZE)
        results = [
            self._to_result(None, face.bbox, self._recognize(image, face.bbox))
            for face in faces
        ]
        return RecognitionResponse(
            faces_detected=len(results),
            recognized_faces=results,
            processing_time_ms=_elapsed_ms(started),
        )

    def verify(self, image: Image, person_code: str) -> VerificationResponse:
        """1:1 verification: is the (single) face in ``image`` this person?

        Raises:
            PersonNotFoundError: Unknown person_code.
            NoEnrolledEmbeddingError: Person has no active embeddings for the model.
            NoFaceDetectedError / MultipleFacesError: Not exactly one face.
        """
        validate_image(image)
        person = self._persons.get_person_by_code(person_code)
        if person is None:
            raise PersonNotFoundError(f"No person with code '{person_code}'")
        person_id = person.id

        face = self._detection.detect_single_face(
            image, max_side=settings.VIDEO_MAX_FRAME_SIZE
        )
        result = self._embedding.generate_embedding_for_bbox(image, face.bbox)
        matches = self._embeddings.search_similar_embeddings(
            result.as_list(),
            model_name=self._config.model_name,
            limit=1,
            person_id=person_id,
        )
        self._end_read()
        if not matches:
            raise NoEnrolledEmbeddingError(
                f"Person '{person_code}' has no active embeddings for "
                f"model '{self._config.model_name}'"
            )
        distance = min(max(matches[0].distance, 0.0), 2.0)  # guard float noise
        return VerificationResponse(
            matched=is_match(distance, self._config.threshold),
            distance=distance,
            similarity=1.0 - distance,
            threshold=self._config.threshold,
        )

    # -- video / webcam ----------------------------------------------------------
    def process_frame(self, frame: Image, frame_number: int) -> FrameResult:
        """Detect, track and (periodically) recognize faces in one frame.

        Works identically for uploaded video and webcam frames. Never raises
        for a single bad frame or a failed recognition: those are logged and
        the frame yields the faces that could be processed. Only unrecoverable
        problems (e.g. the model cannot load) propagate.
        """
        started = time.perf_counter()
        try:
            validate_image(frame)
            detections = self._detection.detect(
                frame, max_side=settings.VIDEO_MAX_FRAME_SIZE
            )
        except (InvalidImageError, FaceDetectionError):
            logger.exception("Frame %s could not be processed; skipping", frame_number)
            return FrameResult(frame_number, [], _elapsed_ms(started))

        tracks = self._tracker.update(
            [d.bbox for d in detections], frame_number,
            [d.detection_confidence for d in detections],
        )
        faces: list[RecognitionResult] = []
        for track in tracks:
            if track.recognition_due(frame_number, self._interval):
                try:
                    outcome = self._recognize(frame, track.bbox)
                except RepositoryError:
                    logger.exception("Database search failed for track %s", track.track_id)
                    outcome = None
                track.record_recognition(outcome, frame_number, self._confirmations)
                logger.debug(
                    "Frame %s track %s recognized as %s",
                    frame_number, track.track_id, track.identity,
                )
            faces.append(self._track_result(track))
        return FrameResult(frame_number, faces, _elapsed_ms(started))

    # -- internals ---------------------------------------------------------------
    def _recognize(self, frame: Image, bbox: BoundingBox) -> RecognitionOutcome | None:
        """Crop -> ArcFace -> Qdrant nearest neighbour -> threshold.

        Returns None if no embedding could be computed (logged). Database
        failures raise ``RepositoryError`` for the caller to handle.
        """
        try:
            result = self._embedding.generate_embedding_for_bbox(frame, bbox)
        except (FaceProcessingError, InvalidImageError) as exc:
            logger.warning("Could not embed face at %s: %s", bbox, exc)
            return None

        matches = self._embeddings.search_similar_embeddings(
            result.as_list(), model_name=self._config.model_name, limit=1
        )
        self._end_read()
        return RecognitionOutcome.from_match(
            matches[0] if matches else None, self._config.threshold
        )

    def _end_read(self) -> None:
        """Release the read transaction so the connection returns to the pool."""
        self._session.rollback()

    def _track_result(self, track: Track) -> RecognitionResult:
        return _build_result(
            track.track_id,
            track.bbox,
            track.matched,
            track.person_id,
            track.person_code,
            track.name,
            track.distance,
            track.similarity,
        )

    def _to_result(
        self, track_id: int | None, bbox: BoundingBox, outcome: RecognitionOutcome | None
    ) -> RecognitionResult:
        outcome = outcome or RecognitionOutcome(matched=False)
        return _build_result(
            track_id,
            bbox,
            outcome.matched,
            outcome.person_id,
            outcome.person_code,
            outcome.name,
            outcome.distance,
            outcome.similarity,
        )


def _build_result(
    track_id: int | None,
    bbox: BoundingBox,
    matched: bool,
    person_id: int | None,
    person_code: str | None,
    name: str | None,
    distance: float | None,
    similarity: float | None,
) -> RecognitionResult:
    return RecognitionResult(
        track_id=track_id,
        person_id=person_id,
        person_code=person_code,
        name=name,
        matched=matched,
        distance=distance,
        similarity=similarity,
        bbox=BoundingBoxSchema.model_validate(bbox),
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0
