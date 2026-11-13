from __future__ import annotations

import pytest

from app.utils.geometry import (
    denormalize_polygon, foot_point, inward_displacement, iou, is_moving_inward, point_in_polygon,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_fm01_foot_point_is_bottom_centre_of_box() -> None:
    assert foot_point((10, 20, 30, 100)) == (20.0, 100)


@pytest.mark.parametrize("point,expected", [((5, 5), True), ((11, 5), False), ((-1, 5), False), ((0, 5), True),
                                            ((10, 10), True), ((5, 10.5), False)])
def test_fm01_point_in_polygon(point, expected) -> None:
    assert point_in_polygon(point, SQUARE) is expected


def test_fm01_point_in_concave_polygon() -> None:
    l_shape = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
    assert point_in_polygon((2, 8), l_shape) is True
    assert point_in_polygon((8, 8), l_shape) is False


def test_fm01_degenerate_polygon_contains_nothing() -> None:
    assert point_in_polygon((1, 1), [(0, 0), (2, 2)]) is False


def test_fm08_roi_polygon_is_resolution_independent() -> None:
    assert denormalize_polygon([(0.5, 0.5)], 640, 480) == [(320.0, 240.0)]


def test_iou_identical_disjoint_and_partial() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)


def test_fm01_inward_displacement_projects_on_direction() -> None:
    assert inward_displacement([(0, 0), (0, 30)], (0, 1)) == pytest.approx(30.0)
    assert inward_displacement([(0, 0), (30, 0)], (0, 1)) == pytest.approx(0.0)   # sliding along the entrance
    assert inward_displacement([(0, 30), (0, 0)], (0, 1)) == pytest.approx(-30.0)  # leaving


def test_fm01_moving_inward_needs_minimum_displacement_over_window() -> None:
    walking_in = [(0, y) for y in range(0, 40, 4)]
    assert is_moving_inward(walking_in, (0, 1), window=10, min_displacement=12.0) is True
    assert is_moving_inward([(0, 5), (0, 8)], (0, 1), window=10, min_displacement=12.0) is False
    assert is_moving_inward([(0, 5)], (0, 1), window=10, min_displacement=12.0) is False


def test_fm01_window_only_looks_at_recent_points() -> None:
    history = [(0, 100), (0, 0)] + [(0, 0)] * 9     # big inward move long ago, standing still now
    assert is_moving_inward([(0, y) for y in (0, 20)] + history, (0, 1), window=5, min_displacement=12.0) is False


def test_zero_direction_is_rejected() -> None:
    with pytest.raises(ValueError):
        inward_displacement([(0, 0), (1, 1)], (0, 0))


@pytest.mark.parametrize("direction,history", [
    ((1, 0), [(0, 0), (20, 0)]), ((-1, 0), [(20, 0), (0, 0)]),
    ((0, 1), [(0, 0), (0, 20)]), ((0, -1), [(0, 20), (0, 0)]),
])
def test_four_inward_directions(direction, history) -> None:
    assert is_moving_inward(history, direction, window=5, min_displacement=12)


def test_jitter_and_standing_still_do_not_count_as_inward() -> None:
    assert not is_moving_inward([(0, 0), (2, -1), (-1, 1), (1, 0)], (1, 0), 4, 12)
    assert not is_moving_inward([(10, 10)] * 5, (0, -1), 5, 12)
