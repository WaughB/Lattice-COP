# SPDX-License-Identifier: Apache-2.0
"""Geography helpers."""

import math

import pytest

from lattice_cop.config import load_settings
from lattice_cop.geo import BoundingBox, distance_nm, heading_quaternion, velocity_enu

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


# --- conversions ---


def test_unit_factors() -> None:
    from lattice_cop import geo  # noqa: PLC0415

    assert geo.KNOTS_TO_MPS == 0.514444
    assert geo.FEET_TO_METERS == 0.3048
    assert geo.FEET_PER_MINUTE_TO_MPS == 0.00508


@pytest.mark.parametrize(
    ("course", "east", "north"),
    [
        (0.0, 0.0, 5.14444),
        (90.0, 5.14444, 0.0),
        (180.0, 0.0, -5.14444),
        (270.0, -5.14444, 0.0),
        (45.0, 3.63767, 3.63767),
    ],
)
def test_velocity_points_along_the_course(course: float, east: float, north: float) -> None:
    e, n, u = velocity_enu(10.0, course)
    assert e == pytest.approx(east, abs=1e-5)
    assert n == pytest.approx(north, abs=1e-5)
    assert u == 0.0


def test_velocity_includes_the_climb_rate() -> None:
    assert velocity_enu(0.0, 0.0, 1000.0) == (0.0, 0.0, pytest.approx(5.08))
    assert velocity_enu(0.0, 0.0, -640.0)[2] == pytest.approx(-3.2512)


@pytest.mark.parametrize(
    ("heading", "yaw_degrees"),
    [(0.0, 90.0), (90.0, 0.0), (180.0, -90.0), (270.0, -180.0), (359.0, -269.0)],
)
def test_heading_becomes_a_yaw_about_the_up_axis(heading: float, yaw_degrees: float) -> None:
    x, y, z, w = heading_quaternion(heading)
    yaw = math.radians(yaw_degrees)
    assert (x, y) == (0.0, 0.0)
    assert z == pytest.approx(math.sin(yaw / 2))
    assert w == pytest.approx(math.cos(yaw / 2))
    assert x * x + y * y + z * z + w * w == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("heading", "east", "north"),
    [
        (0.0, 0.0, 1.0),
        (90.0, 1.0, 0.0),
        (180.0, 0.0, -1.0),
        (270.0, -1.0, 0.0),
        (359.0, -0.01745, 0.99985),
    ],
)
def test_a_heading_north_points_up_the_map(heading: float, east: float, north: float) -> None:
    """Rotating the east axis by the quaternion must give the compass direction."""
    _, _, z, w = heading_quaternion(heading)
    # For a rotation about the up axis, the east unit vector lands on (cos yaw, sin yaw).
    pointed_east = w * w - z * z
    pointed_north = 2 * w * z
    assert pointed_east == pytest.approx(east, abs=1e-5)
    assert pointed_north == pytest.approx(north, abs=1e-5)
