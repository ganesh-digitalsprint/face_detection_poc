"""Scenario definitions A-J (docs/face_mask/SCENARIOS.md): the single source of expected results.

`expected_events` is the number of concealed PEOPLE the scenario contains; each must produce exactly one event and
therefore exactly one alert. Visible / unable-to-assess / not-entering scenarios expect 0.
"""
from __future__ import annotations

from dataclasses import dataclass

# One shared entry ROI for all sample videos: the lower 60% of the frame, people enter by walking up the image.
ROI = "0.05,0.40,0.95,0.40,0.95,0.98,0.05,0.98"
INWARD = "0,-1"


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    expected_events: int
    expected_classification: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("A", "Normal visible face", 0, "VISIBLE"),
    Scenario("B", "Face mask", 1, "CONCEALED"),
    Scenario("C", "Head turned away (nothing covering)", 0, "no alert"),
    Scenario("D", "Group of three, one concealed", 1, "1 CONCEALED, 2 VISIBLE"),
    Scenario("E", "Passing by without entering", 0, "not evaluated"),
    Scenario("F", "Poor light / angle", 0, "UNABLE_TO_ASSESS"),
    Scenario("G", "Covered person lingers", 1, "CONCEALED, one event only"),
    Scenario("H", "Scarf", 1, "CONCEALED"),
    Scenario("I", "Cap hiding face, looking down", 1, "CONCEALED"),
    Scenario("J", "Sunglasses only", 0, "VISIBLE"),
)
