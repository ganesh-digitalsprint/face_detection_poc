import numpy as np
import pytest

from grill_gate_monitoring.services.gate_geometry import GateCalibration, edge_search_diagnostics, measure


def calibration():
    return GateCalibration(
        roi_polygon=[(0, 0), (199, 0), (199, 99), (0, 99)],
        strip_rows=[0.40, 0.42, 0.44], strip_half_height_px=1,
        win_left=(0.05, 0.50), win_right=(0.50, 0.95),
        xL_closed=0.30, xL_open=0.10, xR_closed=0.70, xR_open=0.90,
        max_run_fraction=0.50,
    )


def frame_with_runs(*runs):
    frame = np.full((100, 200, 3), 220, dtype=np.uint8)
    for start, end in runs:
        frame[:, start:end, :] = 0
    return frame


def test_geometry_measures_closed_half_open_progress():
    cal = calibration()
    closed = measure(frame_with_runs((60, 141)), cal)
    middle = measure(frame_with_runs((40, 50), (150, 160)), cal)
    opened = measure(frame_with_runs((20, 30), (170, 180)), cal)

    assert closed["P"] == pytest.approx(0.0, abs=0.02)
    assert middle["P"] == pytest.approx(0.5, abs=0.02)
    assert opened["P"] == pytest.approx(1.0, abs=0.02)
    assert all(result["conf"] == 1.0 for result in (closed, middle, opened))


def test_geometry_ignores_a_wide_dark_object():
    result = measure(frame_with_runs((30, 151), (20, 30), (170, 180)), calibration())
    assert result["xL_px"] != 30
    assert result["xR_px"] != 150


def test_edge_diagnostics_explain_wide_runs_rejected_on_each_side():
    diagnostics = edge_search_diagnostics(frame_with_runs((30, 151)), calibration())
    assert diagnostics["frame_size"] == {"width": 200, "height": 100}
    assert diagnostics["max_run_px"] == 99
    assert "wider than the configured maximum" in diagnostics["edges"]["left"]["reason"]
    assert "wider than the configured maximum" in diagnostics["edges"]["right"]["reason"]

