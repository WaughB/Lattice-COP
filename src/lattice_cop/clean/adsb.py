# SPDX-License-Identifier: Apache-2.0
"""ADS-B cleaning rules for readsb's aircraft.json.

ADS-B Exchange's v2 API uses the same field names, so these rules serve the
fallback source too. Each rule is a pure function; the ``AdsbCleaner`` applies
them in order, remembers the last kept position per aircraft, and counts every
outcome by reason.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Self

from lattice_cop.clean.common import KEPT, Fix, is_position_jump
from lattice_cop.config import Settings
from lattice_cop.geo import FEET_TO_METERS, BoundingBox, distance_nm
from lattice_cop.models import Source, Track
from lattice_cop.sources.readsb import Aircraft, Snapshot

EMERGENCY_SQUAWKS: Final = {
    "7500": "unlawful interference",
    "7600": "radio failure",
    "7700": "general emergency",
}

EMERGENCY_STATUSES: Final = {
    "general": "general emergency",
    "nordo": "radio failure",
    "unlawful": "unlawful interference",
    "downed": "downed aircraft",
}
"""ADS-B emergency states. They set the emergency flag, like the squawks above."""

PRIORITY_STATUSES: Final = {"lifeguard": "medical flight", "minfuel": "minimum fuel"}
"""ADS-B priority states. They are described but are not emergencies."""

EMITTER_CATEGORIES: Final = {
    "A1": "light aircraft",
    "A2": "small aircraft",
    "A3": "large aircraft",
    "A4": "high-vortex large aircraft",
    "A5": "heavy aircraft",
    "A6": "high-performance aircraft",
    "A7": "rotorcraft",
    "B1": "glider",
    "B2": "lighter-than-air",
    "B3": "parachutist",
    "B4": "ultralight",
    "B6": "unmanned aircraft",
    "B7": "space vehicle",
    "C1": "emergency surface vehicle",
    "C2": "service surface vehicle",
    "C3": "point obstacle",
    "C4": "cluster obstacle",
    "C5": "line obstacle",
}
"""ADS-B emitter categories (RTCA DO-260B). ``A0`` and the like mean "no information"."""

POSITION_SOURCES: Final = {
    "adsr": "relayed by a ground station (ADS-R)",
    "tisb": "from ground radar (TIS-B)",
    "mlat": "multilateration",
    "adsc": "satellite (ADS-C)",
}
"""Shown when the data did not come straight from the aircraft. Keyed by the
part of readsb's ``type`` before the underscore."""

DB_MILITARY: Final = 1
DB_PIA: Final = 4
DB_LADD: Final = 8
"""Bits of readsb's ``dbFlags``. PIA and LADD are the two FAA privacy programmes."""

LAST_FIX_TTL_SECONDS: Final = 600.0
"""An aircraft's last kept position is forgotten after this long without a new one."""

# Drop and outcome names, used as counter keys.
NO_POSITION: Final = "no_position"
STALE: Final = "stale"
OUTSIDE_AOI: Final = "outside_aoi"
OUTSIDE_RADIUS: Final = "outside_radius"
NON_ICAO: Final = "non_icao"
POSITION_JUMP: Final = "position_jump"
EMERGENCY: Final = "emergency_squawk"

ALTITUDE_APPROXIMATE: Final = "altitude approximate"
ALTITUDE_UNKNOWN: Final = "altitude unknown"
ON_GROUND: Final = "on ground"

log = logging.getLogger("lattice_cop.clean.adsb")


@dataclass(frozen=True, slots=True)
class AdsbRules:
    """Thresholds for the ADS-B rules. They come from settings."""

    aoi: BoundingBox
    center: tuple[float, float]
    radius_nm: float = 60.0
    max_position_age_seconds: float = 15.0
    max_speed_kn: float = 1000.0
    jump_slack_nm: float = 0.1
    allow_non_icao: bool = False
    geoid_offset_m: float = -26.7

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build the rules from loaded settings."""
        return cls(
            aoi=settings.aoi,
            center=(settings.adsb_center_lat, settings.adsb_center_lon),
            radius_nm=settings.adsb_radius_nm,
            max_position_age_seconds=settings.adsb_max_position_age_seconds,
            max_speed_kn=settings.adsb_max_speed_kn,
            jump_slack_nm=settings.position_jump_slack_nm,
            allow_non_icao=settings.adsb_allow_non_icao,
            geoid_offset_m=settings.geoid_offset_m,
        )


# --- pure rules ---


def height_above_ellipsoid(aircraft: Aircraft, geoid_offset_m: float) -> tuple[float, str | None]:
    """Return the height above the WGS84 ellipsoid in metres, and a note if it is inexact.

    Geometric altitude is already referenced to the ellipsoid. Barometric
    altitude is not, so it is shifted by the local geoid offset and flagged as
    approximate. An aircraft on the ground sits at the geoid offset.
    """
    if aircraft.alt_geom_ft is not None:
        return aircraft.alt_geom_ft * FEET_TO_METERS, None
    if aircraft.on_ground:
        return geoid_offset_m, ON_GROUND
    if aircraft.alt_baro_ft is not None:
        return aircraft.alt_baro_ft * FEET_TO_METERS + geoid_offset_m, ALTITUDE_APPROXIMATE
    return geoid_offset_m, ALTITUDE_UNKNOWN


def clean_text(value: str | None) -> str:
    """Trim the padding readsb leaves on callsigns and similar fields."""
    return value.strip() if value else ""


def display_name(aircraft: Aircraft) -> str:
    """Return the callsign, else the registration, else the hex address."""
    return clean_text(aircraft.flight) or clean_text(aircraft.registration) or aircraft.hex


def emergency_meaning(squawk: str | None) -> str | None:
    """Return what an emergency squawk means, or ``None`` for any other code."""
    return EMERGENCY_SQUAWKS.get(clean_text(squawk))


def clean_angle(value: float | None) -> float | None:
    """Return a compass angle in degrees if it is within 0 to 360, else ``None``."""
    if value is None or not 0 <= value <= 360:  # noqa: PLR2004 - a full circle
        return None
    return value % 360


def clean_ground_speed(value: float | None) -> float | None:
    """Return the ground speed in knots, or ``None`` when missing or negative."""
    return None if value is None or value < 0 else value


def clean_squawk(value: str | None) -> str | None:
    """Return a transponder code if it is four octal digits, else ``None``."""
    squawk = clean_text(value)
    if len(squawk) != 4 or any(digit not in "01234567" for digit in squawk):  # noqa: PLR2004
        return None
    return squawk


def emergency_state(aircraft: Aircraft) -> str | None:
    """Return the emergency the aircraft declares, by squawk or by ADS-B status."""
    return emergency_meaning(aircraft.squawk) or EMERGENCY_STATUSES.get(
        clean_text(aircraft.emergency)
    )


def type_label(aircraft: Aircraft) -> str:
    """Return the type as ``BOEING 737-800 (B738)``, or whichever half is known."""
    name, code = clean_text(aircraft.type_name), clean_text(aircraft.type_code)
    return f"{name} ({code})" if name and code else name or code


def operator_name(aircraft: Aircraft) -> str:
    """Return the owner or operator, unless the aircraft is in an FAA privacy programme."""
    if aircraft.db_flags & (DB_PIA | DB_LADD):
        return ""
    return clean_text(aircraft.operator)


def position_source_note(aircraft: Aircraft) -> str | None:
    """Say how the data arrived when it did not come straight from the aircraft."""
    return POSITION_SOURCES.get(clean_text(aircraft.position_source).partition("_")[0])


def describe(aircraft: Aircraft, altitude_note: str | None) -> str:
    """Build the track description from everything known about the aircraft."""
    registration, operator, year = (
        clean_text(aircraft.registration),
        operator_name(aircraft),
        clean_text(aircraft.year_built),
    )
    squawk, emergency = clean_squawk(aircraft.squawk), emergency_state(aircraft)
    priority = PRIORITY_STATUSES.get(clean_text(aircraft.emergency))
    parts = [
        type_label(aircraft),
        EMITTER_CATEGORIES.get(clean_text(aircraft.category)),
        "military" if aircraft.db_flags & DB_MILITARY else None,
        f"registration {registration}" if registration else None,
        f"operator {operator}" if operator else None,
        f"built {year}" if year else None,
        f"squawk {squawk}" if squawk else None,
        f"EMERGENCY: {emergency}" if emergency else None,
        f"priority: {priority}" if priority else None,
        _feet("barometric altitude", aircraft.alt_baro_ft),
        _feet("selected altitude", aircraft.selected_altitude_ft),
        position_source_note(aircraft),
        altitude_note,
    ]
    return "; ".join(part for part in parts if part)


def _feet(label: str, value: float | None) -> str | None:
    """Format an altitude such as ``barometric altitude 27,000 ft``."""
    return None if value is None else f"{label} {value:,.0f} ft"


# --- the stateful cleaner ---


class AdsbCleaner:
    """Applies the ADS-B rules to aircraft.json snapshots."""

    def __init__(self, rules: AdsbRules) -> None:
        """Create a cleaner with empty memory."""
        self.rules = rules
        self.counts: Counter[str] = Counter()
        self._last: dict[str, Fix] = {}
        self._emergencies: dict[str, str] = {}

    def clean_snapshot(self, snapshot: Snapshot) -> list[Track]:
        """Clean every aircraft in one aircraft.json document."""
        tracks = [self.clean(aircraft, snapshot.now) for aircraft in snapshot.aircraft]
        return [track for track in tracks if track is not None]

    def clean(self, aircraft: Aircraft, snapshot_now: float) -> Track | None:
        """Clean one aircraft.

        Args:
            aircraft: One entry from aircraft.json.
            snapshot_now: The document's ``now``, in seconds since the Unix epoch.

        Returns:
            A track if the aircraft passes every rule, else ``None``.
        """
        outcome = self._apply(aircraft, snapshot_now)
        if isinstance(outcome, Track):
            self.counts[KEPT] += 1
            return outcome
        self.counts[outcome] += 1
        return None

    def _apply(  # noqa: PLR0911 - one return per rule
        self, aircraft: Aircraft, snapshot_now: float
    ) -> Track | str:
        """Return the cleaned track, or the name of the reason it was dropped."""
        rules, position = self.rules, aircraft.position
        if position is None or aircraft.seen_pos is None:
            return NO_POSITION
        if aircraft.seen_pos > rules.max_position_age_seconds:
            return STALE
        latitude, longitude = position
        if not rules.aoi.contains(latitude, longitude):
            return OUTSIDE_AOI
        if distance_nm(*rules.center, latitude, longitude) > rules.radius_nm:
            return OUTSIDE_RADIUS
        if not rules.allow_non_icao and not aircraft.is_icao:
            return NON_ICAO

        at = datetime.fromtimestamp(snapshot_now - aircraft.seen_pos, tz=UTC)
        fix, previous = Fix(latitude, longitude, at), self._last.get(aircraft.hex)
        if previous is not None and is_position_jump(
            previous, fix, max_speed_kn=rules.max_speed_kn, slack_nm=rules.jump_slack_nm
        ):
            return POSITION_JUMP
        self._last[aircraft.hex] = fix

        self._note_emergency(aircraft)
        altitude, note = height_above_ellipsoid(aircraft, rules.geoid_offset_m)
        track = clean_angle(aircraft.track_deg)
        heading = clean_angle(aircraft.true_heading_deg)
        rate = (
            aircraft.geom_rate_fpm if aircraft.geom_rate_fpm is not None else aircraft.baro_rate_fpm
        )
        return Track(
            source=Source.ADSB,
            key=aircraft.hex,
            name=display_name(aircraft),
            latitude=latitude,
            longitude=longitude,
            observed_at=at,
            altitude_hae_m=altitude,
            speed_kn=clean_ground_speed(aircraft.ground_speed_kn),
            course_deg=track,
            heading_deg=heading if heading is not None else track,
            vertical_rate_fpm=rate,
            callsign=clean_text(aircraft.flight) or None,
            registration=clean_text(aircraft.registration) or None,
            description=describe(aircraft, note),
            specific_type=clean_text(aircraft.type_name) or clean_text(aircraft.type_code) or None,
            squawk=clean_squawk(aircraft.squawk),
            pressure_altitude_ft=aircraft.alt_baro_ft,
            emergency=emergency_state(aircraft) is not None,
        )

    def _note_emergency(self, aircraft: Aircraft) -> None:
        """Count and log an emergency squawk once each time an aircraft starts sending it."""
        squawk = clean_text(aircraft.squawk)
        meaning = emergency_meaning(squawk)
        if meaning is None:
            self._emergencies.pop(aircraft.hex, None)
            return
        if self._emergencies.get(aircraft.hex) == squawk:
            return
        self._emergencies[aircraft.hex] = squawk
        self.counts[EMERGENCY] += 1
        log.warning(
            "aircraft is squawking an emergency code",
            extra={"hex": aircraft.hex, "squawk": squawk, "meaning": meaning},
        )

    def prune(self, snapshot_now: float) -> int:
        """Forget aircraft not seen for a while. Returns how many entries went."""
        cutoff = snapshot_now - LAST_FIX_TTL_SECONDS
        old = [key for key, fix in self._last.items() if fix.at.timestamp() < cutoff]
        for key in old:
            del self._last[key]
            self._emergencies.pop(key, None)
        return len(old)

    @property
    def tracked(self) -> int:
        """How many aircraft have a remembered position."""
        return len(self._last)
