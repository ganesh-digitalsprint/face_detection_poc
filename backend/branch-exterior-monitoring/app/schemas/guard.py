from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GuardCreate(BaseModel):
    name: str
    employee_id: str = ""


class Guard(BaseModel):
    id: str
    name: str
    employee_id: str = ""
    photo_paths: list[str] = []
    active: bool = True
    enrolled_at: datetime
