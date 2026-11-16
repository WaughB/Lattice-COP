# SPDX-License-Identifier: Apache-2.0
"""The normalized track shared by both sources.

Cleaning turns an AIS message or a readsb aircraft into a ``Track``. The Lattice
mapping turns a ``Track`` into an entity. Units stay as the sources report them
(knots, degrees, feet per minute) except height, which is already metres above
the WGS84 ellipsoid.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Source(StrEnum):
    """Where a track came from."""

    AIS = "ais"
    ADSB = "adsb"


@dataclass(frozen=True, slots=True)
class Track:
    """One cleaned vessel or aircraft report."""

    source: Source
    key: str
    """MMSI (as text) for a vessel, ICAO hex for an aircraft."""
    name: str
    latitude: float
    longitude: float
    observed_at: datetime
    """When the source says the position was valid (UTC)."""
    altitude_hae_m: float = 0.0
    speed_kn: float | None = None
    course_deg: float | None = None
    """Direction of travel over ground, degrees clockwise from true north."""
    heading_deg: float | None = None
    """Where the bow or nose points; falls back to the course when unknown."""
    vertical_rate_fpm: float | None = None
    callsign: str | None = None
    registration: str | None = None
    description: str = ""
    specific_type: str | None = None
    """What kind of aircraft it is, such as ``BOEING 737-800``."""
    squawk: str | None = None
    """Transponder code: four octal digits."""
    pressure_altitude_ft: float | None = None
    """Barometric altitude as the transponder reports it."""
    emergency: bool = False
    """Whether the aircraft is declaring an emergency."""
