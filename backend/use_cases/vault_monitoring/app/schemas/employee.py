"""Request and response schemas for employee registration."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

EmployeeId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
EmployeeName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=150),
]
OptionalEmployeeField = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: EmployeeId = Field(description="Unique business identifier, e.g. EMP001")
    name: EmployeeName
    department: OptionalEmployeeField | None = None
    designation: OptionalEmployeeField | None = None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: str
    name: str
    department: str | None
    designation: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeRegistrationStatus(BaseModel):
    employee_id: str
    authorization_exists: bool
    authorization_active: bool | None
    face_registered: bool
