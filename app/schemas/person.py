"""Pydantic schemas for person registration.

The face image is not part of these schemas: FastAPI receives it separately as
a multipart file upload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Letters, digits, underscore, dot and hyphen only (safe for URLs and filenames).
PersonCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.\-]+$",
    ),
]
PersonName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class PersonCreate(BaseModel):
    """Data needed to register a person (blank values are rejected)."""

    person_code: PersonCode = Field(description="Unique business code, e.g. P001")
    name: PersonName


class PersonResponse(BaseModel):
    """A stored person (built directly from the ORM object)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    person_code: str
    name: str
    status: Literal["active", "inactive"]
    created_at: datetime


class RegistrationResponse(BaseModel):
    """Result of registering a person with a face."""

    person_id: int
    person_code: str
    name: str
    face_registered: bool
    model_name: str = Field(description="Recognition model that produced the embedding")
    images_enrolled: int = Field(default=1, ge=1, description="Number of persisted face images")
