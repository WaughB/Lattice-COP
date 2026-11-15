# SPDX-License-Identifier: Apache-2.0
"""Geography helpers: the area-of-interest box and distances."""

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
