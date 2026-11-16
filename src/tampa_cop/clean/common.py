# SPDX-License-Identifier: Apache-2.0
"""Rules shared by the AIS and ADS-B cleaners."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from tampa_cop.geo import distance_nm

KEPT: Final = "kept"
"""Counter name for reports that passed every rule."""

SECONDS_PER_HOUR: Final = 3600.0


@dataclass(frozen=True, slots=True)
class Fix:
    """The last position kept for one vessel or aircraft."""

    latitude: float
    longitude: float
    at: datetime


def number(value: object) -> float | None:
    """Return ``value`` as a float if it is a real number, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def is_position_jump(previous: Fix, current: Fix, *, max_speed_kn: float, slack_nm: float) -> bool:
    """Return whether moving from ``previous`` to ``current`` is impossibly fast.

    The allowed distance is the top speed times the time between the two
    positions, plus ``slack_nm`` to absorb position noise and timestamp jitter
    when reports arrive close together.
    """
    hours = abs((current.at - previous.at).total_seconds()) / SECONDS_PER_HOUR
    travelled = distance_nm(
        previous.latitude, previous.longitude, current.latitude, current.longitude
    )
    return travelled > max_speed_kn * hours + slack_nm
