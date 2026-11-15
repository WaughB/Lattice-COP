# SPDX-License-Identifier: Apache-2.0
"""Geography helpers."""

import pytest

from lattice_cop.config import load_settings
from lattice_cop.geo import BoundingBox, distance_nm

TAMPA_BAY = BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)


@pytest.mark.parametrize(
    ("latitude", "longitude", "inside"),
    [
        (27.75, -82.55, True),
        (27.40, -83.00, True),
        (28.20, -82.25, True),
        (27.39, -82.55, False),
        (28.21, -82.55, False),
        (27.75, -83.01, False),
        (27.75, -82.24, False),
    ],
)
def test_contains_includes_the_edges(latitude: float, longitude: float, inside: bool) -> None:
    assert TAMPA_BAY.contains(latitude, longitude) is inside


def test_corners_are_latitude_first() -> None:
    assert TAMPA_BAY.corners() == [[27.40, -83.00], [28.20, -82.25]]


@pytest.mark.usefixtures("token_env")
def test_settings_expose_the_default_area(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AOI_NORTH", "28.5")
    area = load_settings(env_file=None).aoi
    assert area == BoundingBox(south=27.40, west=-83.00, north=28.5, east=-82.25)


def test_one_degree_of_latitude_is_about_sixty_nautical_miles() -> None:
    assert distance_nm(27.0, -82.5, 28.0, -82.5) == pytest.approx(60.04, abs=0.05)


def test_distance_is_zero_for_the_same_point_and_symmetric() -> None:
    assert distance_nm(27.75, -82.55, 27.75, -82.55) == 0.0
    there = distance_nm(27.75, -82.55, 28.20, -82.25)
    back = distance_nm(28.20, -82.25, 27.75, -82.55)
    assert there == pytest.approx(back)
    assert there == pytest.approx(31.4, abs=0.2)


def test_distance_handles_opposite_points() -> None:
    assert distance_nm(0.0, 0.0, 0.0, 180.0) == pytest.approx(10807.3, abs=0.5)
