# Grill Gate Calibration Foundation (Stage 1)

## Assignment document shape

The versioned document is validated by `app.schemas.grill_gate_calibration.GrillGateCalibration` and stored in the existing `camera_use_case_assignments.calibration` JSON field. This example intentionally contains placeholders rather than camera-specific measurements. Replace every placeholder using an actual captured frame and reviewed calibration before saving it; the placeholder document itself is not valid input.

```json
{
  "schema_version": 1,
  "reference_frame": {
    "width": "<captured frame width in pixels>",
    "height": "<captured frame height in pixels>"
  },
  "coordinate_system": "normalized_raw",
  "calibrated_at": "<timezone-aware ISO 8601 timestamp>",
  "sliding_gate": {
    "gate_roi_zone_key": "gate_leaf_roi",
    "closed_reference_position": "<normalized horizontal position>",
    "open_reference_position": "<different normalized horizontal position>",
    "horizontal_movement_direction": "<left_to_right or right_to_left>",
    "position_thresholds": {
      "closed_tolerance": "<normalized image-space tolerance>",
      "open_tolerance": "<normalized image-space tolerance>"
    },
    "confidence_threshold": "<value greater than 0 and at most 1>",
    "state_confirmation_durations": {
      "closed_seconds": "<positive seconds>",
      "opening_seconds": "<positive seconds>",
      "open_seconds": "<positive seconds>",
      "partially_open_seconds": "<positive seconds>",
      "closing_seconds": "<positive seconds>"
    },
    "hysteresis_fraction": "<value greater than 0 and less than 0.5>"
  },
  "directional_crossing": {
    "line_start": { "x": "<normalized x>", "y": "<normalized y>" },
    "line_end": { "x": "<different normalized point x>", "y": "<different normalized point y>" },
    "outside_side": "<left or right of the oriented line>",
    "inside_side": "<the opposite side>",
    "entry_direction": "outside_to_inside",
    "exit_direction": "inside_to_outside",
    "dead_band_fraction": "<positive normalized fraction at most 1>",
    "minimum_crossing_displacement": "<positive normalized displacement at most 2>"
  },
  "monitoring": {
    "thresholds_status": "unset",
    "maximum_continuous_open_seconds": null,
    "crossing_inactivity_seconds": null,
    "minimum_mesh_gathering_count": null,
    "mesh_gathering_seconds": null,
    "suspicious_activity_seconds": null
  }
}
```

Numeric monitoring thresholds intentionally have no defaults. `unset` means no business threshold is configured; use `provisional` or `approved` when values are provided. An `approved` document must provide all five monitoring thresholds. A suspicious-activity duration cannot be shorter than the gathering duration.

Coordinates and frame dimensions are validated as supplied. A frame-size mismatch is rejected and requires recalibration; there is no silent coordinate rescaling. Calibration is assignment-scoped. Existing assignments without calibration remain valid.

## API

No new endpoint was added. Create and update calibration through the existing authenticated registry assignment routes:

- `POST /api/v1/regions/assignments` with `use_case: "grill_gate"` and optional `calibration`.
- `PATCH /api/v1/regions/assignments/{assignment_id}` with `calibration`.
- `GET /api/v1/regions/assignments` to read assignments and their calibration.

The existing assignment API key authentication remains in force. Calibration is validated only for Grill Gate assignments. Other use cases retain their current calibration payload behavior.

## Zones

Grill Gate zone types are configured in `backend/use_cases/vault_monitoring/config/use_cases/grill-gate/zone_types.yaml`. All zones are polygons. `gate_crossing` is the corridor/region; the directional line belongs to assignment calibration and is not represented by a polygon.

Grill Gate polygons must use `normalized_raw` coordinates. No zones or calibration values are created by this stage.

## Stage 1 scope boundary

This foundation does not add camera workers, frame fan-out, detection, tracking, gate-state estimation, crossing detection, timers, monitoring events, alerts, or monitoring UI. Those belong to later approved stages.
