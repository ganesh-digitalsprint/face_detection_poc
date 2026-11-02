"""Pydantic schemas for face detection.
   face.py contains the request and response models for the face detection endpoint.
``distance`` is lower-is-better; ``similarity`` is ``1 - cosine distance``.
Neither is a probability or a confidence percentage.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BoundingBox(BaseModel):
    """Face rectangle in pixel coordinates (top-left origin)."""

    # from_attributes lets this be built directly from the internal
    # app.utils.image.BoundingBox dataclass.
    model_config = ConfigDict(from_attributes=True)

    x: int = Field(ge=0, description="Left edge in pixels")
    y: int = Field(ge=0, description="Top edge in pixels")
    width: int = Field(gt=0, description="Box width in pixels")
    height: int = Field(gt=0, description="Box height in pixels")


class DetectedFace(BaseModel):
    """One detected face.

    Detection alone fills only ``bbox`` and ``detection_confidence``; the
    tracking and identity fields stay null.
    """

    bbox: BoundingBox
    detection_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Detector score, only when the detector provides one",
    )
    track_id: int | None = Field(
        default=None,
        ge=0,
        description="Temporary per-session track number (null for single images)",
    )
    person_id: int | None = Field(default=None, description="Set only after recognition")
    name: str | None = Field(default=None, description="Set only after recognition")
    similarity: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="1 - cosine distance. Derived value, NOT a probability",
    )
    distance: float | None = Field(
        default=None,
        ge=0.0,
        description="Embedding distance; lower means more alike. NOT a probability",
    )


class FaceDetectionResponse(BaseModel):
    """Response of the face detection endpoint."""

    faces_detected: int = Field(ge=0)
    faces: list[DetectedFace]

    @model_validator(mode="after")
    def _count_matches_faces(self) -> Self:
        if self.faces_detected != len(self.faces):
            raise ValueError("faces_detected must equal the number of faces")
        return self