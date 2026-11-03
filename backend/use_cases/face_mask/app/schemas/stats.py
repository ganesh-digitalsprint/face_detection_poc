from __future__ import annotations

from pydantic import BaseModel


class StatsSummary(BaseModel):
    entries: int = 0
    visible: int = 0
    concealed: int = 0
    unable_to_assess: int = 0
    open_reviews: int = 0
    by_camera: dict[str, int] = {}
    by_hour: list[int] = [0] * 24
