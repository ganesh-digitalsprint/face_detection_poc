"""Schemas for creating an employee's vault authorization record."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints


class AuthorizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: StrictBool = False
    authorization_reason: str | None = None
    authorized_by: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=50)] = None
    remarks: str | None = None


class AuthorizationResponse(BaseModel):
    id: int
    employee_id: str
    is_active: bool
    authorized_at: datetime | None
    deauthorized_at: datetime | None
    face_registered: bool
    authorization_reason: str | None
    authorized_by: str | None
    deauthorized_by: str | None
    remarks: str | None
    created_at: datetime
    updated_at: datetime
