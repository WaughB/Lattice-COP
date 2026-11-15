# SPDX-License-Identifier: Apache-2.0
"""Geography helpers."""

import pytest

from lattice_cop.geo import BoundingBox
from lattice_cop.config import load_settings

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
