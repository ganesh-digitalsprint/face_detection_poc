from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from grill_gate_monitoring.schemas.calibration import GrillGateCalibration
from app.services.registry_config import load_zone_types


def valid_calibration(**overrides):
    # Synthetic unit-test fixture only; this is not a real camera calibration.
    value = {
        "schema_version": 1,
        "reference_frame": {"width": 1920, "height": 1080},
        "coordinate_system": "normalized_raw",
        "calibrated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "sliding_gate": {
            "closed_reference_position": 0.2,
            "open_reference_position": 0.8,
            "horizontal_movement_direction": "left_to_right",
            "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
            "confidence_threshold": 0.8,
            "state_confirmation_durations": {
                "closed_seconds": 1,
                "opening_seconds": 0.5,
                "open_seconds": 1,
                "partially_open_seconds": 0.5,
                "closing_seconds": 0.5,
            },
            "hysteresis_fraction": 0.05,
        },
        "directional_crossing": {
            "line_start": {"x": 0.5, "y": 0.2},
            "line_end": {"x": 0.5, "y": 0.8},
            "outside_side": "left",
            "inside_side": "right",
            "dead_band_fraction": 0.02,
            "minimum_crossing_displacement": 0.05,
        },
    }
    value.update(overrides)
    return value


def test_grill_gate_zone_metadata_adds_required_types_and_preserves_existing():
    types = {item["key"]: item for item in load_zone_types("grill_gate")}
    assert set(types) == {
        "gate_leaf_roi", "gate_approach", "gate_trigger", "gate_crossing", "gate_interior", "mesh_area",
    }
    assert "physical sliding gate leaf" in types["gate_leaf_roi"]["description"]
    assert "outside approach" in types["gate_approach"]["description"].lower()
    assert "threshold" in types["gate_trigger"]["description"].lower()
    assert "virtual line" in types["gate_crossing"]["description"]
    assert "bank-premises" in types["gate_interior"]["description"].lower()
    assert "group-presence" in types["mesh_area"]["description"]


def test_other_use_case_zone_metadata_is_unchanged():
    assert {item["key"] for item in load_zone_types("branch_exterior")} == {
        "entrance", "atm", "side_lane", "forecourt", "rear", "restricted", "other",
    }
    assert load_zone_types("vault_room") == ()


def test_valid_calibration_and_unset_business_thresholds():
    calibration = GrillGateCalibration.model_validate(valid_calibration())
    assert calibration.schema_version == 1
    assert calibration.coordinate_system == "normalized_raw"
    assert calibration.monitoring.thresholds_status == "unset"
    assert calibration.monitoring.maximum_continuous_open_seconds is None
    calibration.validate_frame_dimensions(1920, 1080)


def test_directional_line_is_optional_for_three_zone_reference_calibration():
    document = valid_calibration()
    document.pop("directional_crossing")
    calibration = GrillGateCalibration.model_validate(document)
    assert calibration.directional_crossing is None


@pytest.mark.parametrize("patch, message", [
    ({"coordinate_system": "normalized_cropped_analysis"}, "coordinate_system"),
    ({"schema_version": 2}, "schema_version"),
    ({"reference_frame": {"width": 0, "height": 1080}}, "width"),
    ({"calibrated_at": "2026-01-01T00:00:00"}, "timezone"),
    ({"sliding_gate": {"closed_reference_position": 0.5, "open_reference_position": 0.5,
      "horizontal_movement_direction": "left_to_right",
      "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
      "confidence_threshold": 0.8,
      "state_confirmation_durations": {"closed_seconds": 1, "opening_seconds": 1, "open_seconds": 1,
       "partially_open_seconds": 1, "closing_seconds": 1}, "hysteresis_fraction": 0.05}}, "distinguishable"),
    ({"sliding_gate": {"closed_reference_position": 0.2, "open_reference_position": 0.8,
      "horizontal_movement_direction": "right_to_left",
      "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
      "confidence_threshold": 0.8,
      "state_confirmation_durations": {"closed_seconds": 1, "opening_seconds": 1, "open_seconds": 1,
       "partially_open_seconds": 1, "closing_seconds": 1}, "hysteresis_fraction": 0.05}}, "movement_direction"),
    ({"directional_crossing": {"line_start": {"x": 0.5, "y": 0.5}, "line_end": {"x": 0.5, "y": 0.5},
      "outside_side": "left", "inside_side": "right", "dead_band_fraction": 0.02,
      "minimum_crossing_displacement": 0.05}}, "distinct"),
    ({"directional_crossing": {"line_start": {"x": 0.5, "y": 0.2}, "line_end": {"x": 0.5, "y": 0.8},
      "outside_side": "left", "inside_side": "left", "dead_band_fraction": 0.02,
      "minimum_crossing_displacement": 0.05}}, "opposite sides"),
    ({"sliding_gate": {"closed_reference_position": 0.2, "open_reference_position": 0.8,
      "horizontal_movement_direction": "left_to_right",
      "position_thresholds": {"closed_tolerance": 0.4, "open_tolerance": 0.4},
      "confidence_threshold": 0.8,
      "state_confirmation_durations": {"closed_seconds": 1, "opening_seconds": 1, "open_seconds": 1,
       "partially_open_seconds": 1, "closing_seconds": 1}, "hysteresis_fraction": 0.05}}, "must not overlap"),
    ({"monitoring": {"maximum_continuous_open_seconds": 300}}, "thresholds_status"),
    ({"monitoring": {"thresholds_status": "approved", "maximum_continuous_open_seconds": 300}}, "all five"),
])
def test_invalid_calibration_is_rejected(patch, message):
    value = valid_calibration()
    value.update(patch)
    with pytest.raises(ValidationError, match=message):
        GrillGateCalibration.model_validate(value)


def test_frame_dimension_mismatch_requires_recalibration_without_rescaling():
    calibration = GrillGateCalibration.model_validate(valid_calibration())
    with pytest.raises(ValueError, match="Frame dimensions mismatch.*recalibrate"):
        calibration.validate_frame_dimensions(1280, 720)


def test_monitoring_thresholds_can_be_marked_provisional_or_approved():
    provisional = valid_calibration()
    provisional["monitoring"] = {
        "thresholds_status": "provisional",
        "crossing_inactivity_seconds": 300,
    }
    assert GrillGateCalibration.model_validate(provisional).monitoring.thresholds_status == "provisional"

    approved = valid_calibration()
    approved["monitoring"] = {
        "thresholds_status": "approved",
        "maximum_continuous_open_seconds": 600,
        "crossing_inactivity_seconds": 300,
        "minimum_mesh_gathering_count": 3,
        "mesh_gathering_seconds": 60,
        "suspicious_activity_seconds": 300,
    }
    assert GrillGateCalibration.model_validate(approved).monitoring.thresholds_status == "approved"
