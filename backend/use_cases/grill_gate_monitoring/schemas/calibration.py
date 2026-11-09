"""Validated, versioned configuration for Grill Gate camera assignments.

This is configuration only. It contains no detector, worker, or monitoring logic.
Coordinates use normalized raw-frame space and are never rescaled implicitly.
"""
from __future__ import annotations

from datetime import datetime
from math import hypot
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveSeconds = Annotated[float, Field(gt=0.0, le=86_400.0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceFrame(StrictModel):
    width: int = Field(ge=1, le=16_384)
    height: int = Field(ge=1, le=16_384)


class Point2D(StrictModel):
    x: UnitInterval
    y: UnitInterval


class GatePositionThresholds(StrictModel):
    """Normalized progress-space tolerance around the closed/open references."""

    closed_tolerance: UnitInterval
    open_tolerance: UnitInterval


class GateStateConfirmation(StrictModel):
    closed_seconds: PositiveSeconds
    opening_seconds: PositiveSeconds
    open_seconds: PositiveSeconds
    partially_open_seconds: PositiveSeconds
    closing_seconds: PositiveSeconds


class SlidingGateCalibration(StrictModel):
    """Calibration values for the normalized gate progress measurement.

    Geometry-based detection treats 0.0 and 1.0 as closed/open progress endpoints,
    not image coordinates. Position tolerances are fractions of that span. A 0.5
    confidence threshold accepts a single-leaf measurement. For the bi-parting door,
    ``left_to_right`` means combined progress increases as it opens.
    """

    gate_roi_zone_key: Literal["gate_leaf_roi"] = "gate_leaf_roi"
    closed_reference_position: UnitInterval
    open_reference_position: UnitInterval
    horizontal_movement_direction: Literal["left_to_right", "right_to_left"]
    position_thresholds: GatePositionThresholds
    confidence_threshold: Annotated[float, Field(gt=0.0, le=1.0)]
    state_confirmation_durations: GateStateConfirmation
    hysteresis_fraction: Annotated[float, Field(gt=0.0, lt=0.5)]

    @model_validator(mode="after")
    def references_and_thresholds_are_distinguishable(self):
        separation = abs(self.open_reference_position - self.closed_reference_position)
        if separation <= 1e-6:
            raise ValueError("closed_reference_position and open_reference_position must be distinguishable")
        if self.position_thresholds.closed_tolerance + self.position_thresholds.open_tolerance >= separation:
            raise ValueError("closed/open position tolerances must not overlap the calibrated positions")
        moves_right = self.horizontal_movement_direction == "left_to_right"
        if (moves_right and self.open_reference_position <= self.closed_reference_position) or (
            not moves_right and self.open_reference_position >= self.closed_reference_position
        ):
            raise ValueError("reference positions must agree with horizontal_movement_direction")
        return self


class CrossingCalibration(StrictModel):
    line_start: Point2D
    line_end: Point2D
    outside_side: Literal["left", "right"]
    inside_side: Literal["left", "right"]
    entry_direction: Literal["outside_to_inside"] = "outside_to_inside"
    exit_direction: Literal["inside_to_outside"] = "inside_to_outside"
    dead_band_fraction: Annotated[float, Field(gt=0.0, le=1.0)]
    minimum_crossing_displacement: Annotated[float, Field(gt=0.0, le=2.0)]

    @model_validator(mode="after")
    def line_is_valid_and_sides_are_opposed(self):
        if hypot(self.line_end.x - self.line_start.x, self.line_end.y - self.line_start.y) <= 1e-6:
            raise ValueError("line_start and line_end must be distinct")
        if self.outside_side == self.inside_side:
            raise ValueError("outside_side and inside_side must be opposite sides of the line")
        return self


class MeshAndTimerSettings(StrictModel):
    """Business thresholds have no silent numeric defaults; None means unconfigured."""

    thresholds_status: Literal["unset", "provisional", "approved"] = "unset"
    maximum_continuous_open_seconds: PositiveSeconds | None = None
    crossing_inactivity_seconds: PositiveSeconds | None = None
    minimum_mesh_gathering_count: int | None = Field(default=None, ge=1, le=500)
    mesh_gathering_seconds: PositiveSeconds | None = None
    suspicious_activity_seconds: PositiveSeconds | None = None

    @model_validator(mode="after")
    def status_matches_values(self):
        values = (
            self.maximum_continuous_open_seconds,
            self.crossing_inactivity_seconds,
            self.minimum_mesh_gathering_count,
            self.mesh_gathering_seconds,
            self.suspicious_activity_seconds,
        )
        configured = [value is not None for value in values]
        if any(configured) and self.thresholds_status == "unset":
            raise ValueError("Set thresholds_status to 'provisional' or 'approved' when providing business thresholds")
        if self.thresholds_status == "approved" and not all(configured):
            raise ValueError("Approved thresholds require all five monitoring values")
        if (self.mesh_gathering_seconds is not None and self.suspicious_activity_seconds is not None
                and self.suspicious_activity_seconds < self.mesh_gathering_seconds):
            raise ValueError("suspicious_activity_seconds must be greater than or equal to mesh_gathering_seconds")
        return self


class GrillGateCalibration(StrictModel):
    """Complete calibration document stored on one Grill Gate assignment."""

    schema_version: Literal[1] = 1
    reference_frame: ReferenceFrame
    coordinate_system: Literal["normalized_raw"] = "normalized_raw"
    calibrated_at: datetime
    sliding_gate: SlidingGateCalibration
    directional_crossing: CrossingCalibration | None = None
    monitoring: MeshAndTimerSettings = Field(default_factory=MeshAndTimerSettings)

    @model_validator(mode="after")
    def calibration_timestamp_has_timezone(self):
        if self.calibrated_at.tzinfo is None or self.calibrated_at.utcoffset() is None:
            raise ValueError("calibrated_at must include a timezone")
        return self

    def validate_frame_dimensions(self, width: int, height: int) -> None:
        """Reject a frame mismatch; normalized values are never silently rescaled."""
        if width != self.reference_frame.width or height != self.reference_frame.height:
            raise ValueError(
                f"Frame dimensions mismatch: calibration is {self.reference_frame.width}x"
                f"{self.reference_frame.height}, received {width}x{height}; recalibrate this assignment"
            )


def default_video_calibration(width: int, height: int) -> dict:
    """Build a frame-matched calibration from the existing standard gate-state values.

    The optional Three-Zone crossing path needs endpoint polygons, not a virtual line.
    No image-space endpoint measurements or polygon coordinates are synthesized here.
    """
    value = {
        "schema_version": 1,
        "reference_frame": {"width": width, "height": height},
        "coordinate_system": "normalized_raw",
        "calibrated_at": datetime.now().astimezone().isoformat(),
        "sliding_gate": {
            "gate_roi_zone_key": "gate_leaf_roi",
            "closed_reference_position": 0.0,
            "open_reference_position": 1.0,
            "horizontal_movement_direction": "left_to_right",
            "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
            "confidence_threshold": 0.5,
            "state_confirmation_durations": {"closed_seconds": 0.5, "opening_seconds": 0.3,
                "open_seconds": 0.5, "partially_open_seconds": 1.0, "closing_seconds": 0.3},
            "hysteresis_fraction": 0.05,
        },
        "monitoring": {"thresholds_status": "unset"},
    }
    return GrillGateCalibration.model_validate(value).model_dump(mode="json")


def validate_grill_gate_calibration(value: dict | None) -> dict | None:
    """Validate and normalize an optional Grill Gate assignment calibration."""
    if value is None:
        return None
    return GrillGateCalibration.model_validate(value).model_dump(mode="json")
