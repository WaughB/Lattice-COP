# SPDX-License-Identifier: Apache-2.0
"""Geography helpers: the area-of-interest box and distances."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A box in decimal degrees. It must not cross the antimeridian."""

    south: float
    west: float
    north: float
    east: float

    def contains(self, latitude: float, longitude: float) -> bool:
        """Return whether a point is inside the box, edges included."""
        return self.south <= latitude <= self.north and self.west <= longitude <= self.east

    def corners(self) -> list[list[float]]:
        """Return ``[[south, west], [north, east]]``: latitude first, as AISStream expects."""
        return [[self.south, self.west], [self.north, self.east]]


EARTH_RADIUS_NM = 3440.065
"""Mean Earth radius in nautical miles."""


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two points, in nautical miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    half_dphi = (phi2 - phi1) / 2
    half_dlambda = math.radians(lon2 - lon1) / 2
    a = math.sin(half_dphi) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(half_dlambda) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


FEET_TO_METERS = 0.3048
