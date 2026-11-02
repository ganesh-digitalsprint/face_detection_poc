"""Pydantic schemas for recognition and verification.

Vocabulary used in every field description:
    distance:   lower means more alike (cosine distance for ArcFace).
    similarity: ``1 - cosine distance``; derived, NOT a probability.
    threshold:  maximum distance accepted as a match, from configuration.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.face import BoundingBox


class RecognitionResult(BaseModel):
    """Recognition outcome for one face.

    Unknown faces have ``matched=False`` and null identity fields.
    ``track_id`` is temporary and belongs to one video/session; it is never a
    person identifier.
    """

    track_id: int | None = Field(
        default=None,
        ge=0,
        description="Temporary per-session track number (null for single images)",
    )
    person_id: int | None = None
    person_code: str | None = None
    name: str | None = None
    matched: bool
    distance: float | None = Field(
        default=None,
        ge=0.0,
        description="Distance to the nearest stored embedding; lower = more alike",
    )
    similarity: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="1 - cosine distance. Derived value, NOT a probability",
    )
    bbox: BoundingBox

    @model_validator(mode="after")
    def _identity_matches_flag(self) -> Self:
        identity = (self.person_id, self.person_code, self.name)
        if self.matched and any(v is None for v in identity):
            raise ValueError("A matched face must have person_id, person_code and name")
        if not self.matched and any(v is not None for v in identity):
            raise ValueError("An unmatched (unknown) face must not carry an identity")
        return self


class RecognitionResponse(BaseModel):
    """Response of the identify endpoint: one entry per detected face."""

    faces_detected: int = Field(ge=0)
    recognized_faces: list[RecognitionResult] = Field(
        description="One result per detected face; check `matched` for unknowns"
    )
    processing_time_ms: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _count_matches_faces(self) -> Self:
        if self.faces_detected != len(self.recognized_faces):
            raise ValueError("faces_detected must equal the number of results")
        return self


class VerificationResponse(BaseModel):
    """Response of the 1:1 verify endpoint (matched when distance <= threshold)."""

    matched: bool
    distance: float = Field(ge=0.0, description="Lower = more alike. NOT a probability")
    similarity: float = Field(
        ge=-1.0, le=1.0, description="1 - cosine distance. NOT a probability"
    )
    threshold: float = Field(gt=0.0, description="Maximum distance accepted as a match")