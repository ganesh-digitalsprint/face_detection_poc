# Grill Gate gate-state integration

The Grill Gate capture worker remains capture-only. `GrillGateStateDetector` consumes its read-only frame subscription, reads the enabled `gate_leaf_roi` zone and assignment calibration from the shared registry, and reports a gate state. This code runs inside the existing `backend/use_cases/vault_monitoring` application; it does not need a second backend app or a database migration.

## Calibration meaning

The geometry measurement returns progress `P`, where `0` is closed and `1` is open. For geometry-based detection, `sliding_gate.closed_reference_position` and `open_reference_position` are progress-space endpoints, not image positions. Tolerances are fractions of that span. A confidence threshold of `0.5` accepts a single-leaf measurement. `left_to_right` means the bi-parting door's combined progress increases as it opens. The supplied `grill_gate_calibration_example.json` is a complete schema-version 1 assignment calibration.

The detector rejects live frame dimensions that differ from `calibration.reference_frame`; it never rescales the zone or calibration.

## Configure geometry tuning

Store tuning in the gate ROI zone's `properties.gate_geometry`. Zone PATCH replaces the complete `properties` object, so include any other properties that should remain:

```http
PATCH /api/v1/regions/assignments/{assignment_id}/zones/{zone_id}
Content-Type: application/json
```

```json
{
  "properties": {
    "gate_geometry": {
      "strip_rows": [0.39, 0.41, 0.43],
      "strip_half_height_px": 3,
      "win_left": [0.08, 0.45],
      "win_right": [0.30, 0.72],
      "xL_closed": 0.37,
      "xL_open": 0.19,
      "xR_closed": 0.37,
      "xR_open": 0.63,
      "max_run_fraction": 0.12,
      "anchors": []
    }
  }
}
```

Only one enabled `gate_leaf_roi` is allowed per Grill Gate assignment. Geometry fractions must be in `[0, 1]`; left/right windows must be ordered; the open/closed endpoint order must match the moving leaves. The backend rejects unknown tuning fields and invalid values with HTTP 422.

Set the complete assignment calibration through the shared registry assignment endpoint:

```http
PATCH /api/v1/regions/assignments/{assignment_id}
Content-Type: application/json
```

```json
{
  "calibration": {
    "schema_version": 1,
    "reference_frame": {"width": 2560, "height": 1440},
    "coordinate_system": "normalized_raw",
    "calibrated_at": "2026-11-05T12:00:00+05:30",
    "sliding_gate": {
      "gate_roi_zone_key": "gate_leaf_roi",
      "closed_reference_position": 0.0,
      "open_reference_position": 1.0,
      "horizontal_movement_direction": "left_to_right",
      "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
      "confidence_threshold": 0.5,
      "state_confirmation_durations": {
        "closed_seconds": 0.5, "opening_seconds": 0.3, "open_seconds": 0.5,
        "partially_open_seconds": 1.0, "closing_seconds": 0.3
      },
      "hysteresis_fraction": 0.05
    },
    "directional_crossing": {
      "line_start": {"x": 0.4, "y": 0.55}, "line_end": {"x": 0.52, "y": 0.6},
      "outside_side": "left", "inside_side": "right",
      "dead_band_fraction": 0.05, "minimum_crossing_displacement": 0.02
    },
    "monitoring": {"thresholds_status": "unset"}
  }
}
```

## Offline tuning

Run from `backend/use_cases/vault_monitoring`:

```powershell
python scripts/gate_offline_check.py --video C:\videos\gate.mp4 --zones ..\..\..\docs\grill_gate_docs\grill_gate_zones.json --output-dir gate-offline-output --closed-t 2.0 --open-t 8.0
```

The tool writes `gate-progress.csv` and `gate-debug.mp4`. If matplotlib is installed, it also writes `gate-progress.png`. The measured endpoint fractions are printed; copy them into `properties.gate_geometry` and review the output over representative footage before using the live detector. The optional plotting dependency can be installed with `pip install -e ".[offline]"`.

## Runtime and known limits

Connecting an assigned Grill Gate worker starts its state detector. Disconnect and app shutdown stop the detector before stopping capture. `GET /api/v1/grill-gate/assignments/{assignment_id}/gate-state` returns state, progress, confidence, and error metadata; it never returns frames or camera source references. The frontend polls this endpoint while the worker is connected. Uploaded browser videos remain local and do not start the detector.

Geometry strips and thresholds are starting values for Windows and must be tuned on real footage. Camera-shift detection using `anchors` is not implemented. Occlusion filtering uses the maximum dark-run width plus hold-last-state; a thin object about the width of a door stile may still be mistaken for one. The motion threshold of `0.10` progress per second is an initial estimate that may need tuning. These measurements do not implement crossing detection, mesh monitoring, or alerts.
