# SPDX-License-Identifier: Apache-2.0
"""AIS cleaning rules for AISStream messages.

"Not available" values follow ITU-R M.1371: latitude 91, longitude 181,
speed 102.3 kn, course 360, heading 511. Each rule is a pure function; the
``AisCleaner`` applies them in order, remembers the last kept position and the
static data per vessel, and counts every outcome by reason.
"""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final, Self

from tampa_cop.clean.common import KEPT, Fix, is_position_jump, number
from tampa_cop.config import Settings
from tampa_cop.geo import BoundingBox
from tampa_cop.models import Source, Track

POSITION_TYPES: Final = frozenset({"PositionReport", "StandardClassBPositionReport"})
STATIC_TYPES: Final = frozenset({"ShipStaticData", "StaticDataReport"})

MAX_LATITUDE: Final = 90.0
MAX_LONGITUDE: Final = 180.0
"""AIS sends latitude 91 and longitude 181 for "not available"; both fall outside these."""
SPEED_NOT_AVAILABLE_KN: Final = 102.3
COURSE_NOT_AVAILABLE_DEG: Final = 360.0
HEADING_NOT_AVAILABLE_DEG: Final = 511.0
MMSI_DIGITS: Final = 9
VESSEL_MMSI_FIRST_DIGITS: Final = frozenset("234567")

LAST_FIX_TTL_SECONDS: Final = 3600.0
"""A vessel's last kept position is forgotten after this long without a new one."""

# Drop and outcome names, used as counter keys.
MALFORMED: Final = "malformed"
UNSUPPORTED: Final = "unsupported"
INVALID_POSITION: Final = "invalid_position"
OUTSIDE_AOI: Final = "outside_aoi"
MMSI_NOT_VESSEL: Final = "mmsi_not_vessel"
STALE: Final = "stale"
DUPLICATE: Final = "duplicate"
POSITION_JUMP: Final = "position_jump"
INVALID_STATIC: Final = "invalid_static"
STATIC_CACHED: Final = "static_cached"

_SHIP_TYPES_EXACT: Final = {
    30: "Fishing",
    31: "Towing",
    32: "Towing",
    33: "Dredging or underwater operations",
    34: "Diving operations",
    35: "Military operations",
    36: "Sailing",
    37: "Pleasure craft",
    50: "Pilot vessel",
    51: "Search and rescue vessel",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution vessel",
    55: "Law enforcement",
    58: "Medical transport",
}
_SHIP_TYPES_BY_TENS: Final = {
    2: "Wing in ground",
    4: "High-speed craft",
    6: "Passenger",
    7: "Cargo",
    8: "Tanker",
    9: "Other type",
}
_NAV_STATUS: Final = {
    0: "under way using engine",
    1: "at anchor",
    2: "not under command",
    3: "restricted manoeuvrability",
    4: "constrained by draught",
    5: "moored",
    6: "aground",
    7: "engaged in fishing",
    8: "under way sailing",
}


@dataclass(frozen=True, slots=True)
class AisRules:
    """Thresholds for the AIS rules. They come from settings."""

    aoi: BoundingBox
    max_age_seconds: float = 300.0
    max_speed_kn: float = 50.0
    jump_slack_nm: float = 0.1
    allow_non_vessel_mmsi: bool = False
    static_cache_seconds: float = 21600.0

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build the rules from loaded settings."""
        return cls(
            aoi=settings.aoi,
            max_age_seconds=settings.ais_max_age_seconds,
            max_speed_kn=settings.ais_max_speed_kn,
            jump_slack_nm=settings.position_jump_slack_nm,
            allow_non_vessel_mmsi=settings.ais_allow_non_vessel_mmsi,
            static_cache_seconds=settings.ais_static_cache_seconds,
        )


@dataclass(frozen=True, slots=True)
class StaticData:
    """What a vessel says about itself, merged from its static messages."""

    updated_at: datetime
    name: str = ""
    callsign: str = ""
    ship_type: int | None = None
    length_m: int | None = None
    beam_m: int | None = None
    destination: str = ""


# --- pure rules ---


def parse_time_utc(value: object) -> datetime | None:
    """Parse AISStream's ``MetaData.time_utc``, or return ``None``.

    The format is ``2026-01-01 12:00:00.123456789 +0000 UTC``: nanoseconds and
    a trailing zone name, neither of which ``datetime`` reads directly.
    """
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) < 2:  # noqa: PLR2004 - a date and a time
        return None
    clock, _, fraction = parts[1].partition(".")
    micros = (fraction[:6] or "0").ljust(6, "0")
    offset = parts[2] if len(parts) > 2 else "+0000"  # noqa: PLR2004 - optional offset
    try:
        parsed = datetime.strptime(
            f"{parts[0]} {clock}.{micros} {offset}", "%Y-%m-%d %H:%M:%S.%f %z"
        )
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def is_valid_position(valid: object, latitude: float, longitude: float) -> bool:
    """Return whether a position message carries a usable position.

    Latitude 91 and longitude 181 mean "not available"; anything outside the
    globe is treated the same way.
    """
    if valid is False:
        return False
    return abs(latitude) <= MAX_LATITUDE and abs(longitude) <= MAX_LONGITUDE


def is_vessel_mmsi(mmsi: int) -> bool:
    """Return whether an MMSI belongs to a ship: nine digits, first digit 2 to 7.

    Other ranges are coast stations, aids to navigation, search-and-rescue
    aircraft, beacons and similar.
    """
    text = str(mmsi)
    return len(text) == MMSI_DIGITS and text[0] in VESSEL_MMSI_FIRST_DIGITS


def is_stale(message_time: datetime, now: datetime, max_age_seconds: float) -> bool:
    """Return whether a message is older than the allowed age."""
    return (now - message_time).total_seconds() > max_age_seconds


def is_duplicate(previous: Fix | None, current: Fix) -> bool:
    """Return whether a position repeats the last kept one exactly: same place, same time."""
    return previous is not None and previous == current


def clean_speed(sog: float | None) -> float | None:
    """Return speed over ground in knots, or ``None`` when it is not available."""
    if sog is None or sog < 0 or sog >= SPEED_NOT_AVAILABLE_KN:
        return None
    return sog


def clean_course(cog: float | None) -> float | None:
    """Return course over ground in degrees, or ``None`` when it is not available."""
    if cog is None or cog < 0 or cog >= COURSE_NOT_AVAILABLE_DEG:
        return None
    return cog


def clean_heading(true_heading: float | None, course: float | None) -> float | None:
    """Return the true heading, falling back to the cleaned course, else ``None``."""
    if true_heading is not None and 0 <= true_heading < COURSE_NOT_AVAILABLE_DEG:
        return true_heading
    return course


def clean_text(value: object) -> str:
    """Trim AIS padding (``@``) and spaces from a name, call sign or destination."""
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("@ ").strip()


def display_name(name: str, mmsi: int) -> str:
    """Return the ship name, or ``MMSI 123456789`` when there is none."""
    return name or f"MMSI {mmsi}"


def ship_type_name(code: int | None) -> str | None:
    """Return a readable name for an AIS ship type code, or ``None`` if unknown."""
    if code is None:
        return None
    return _SHIP_TYPES_EXACT.get(code) or _SHIP_TYPES_BY_TENS.get(code // 10)


def nav_status_name(code: int | None) -> str | None:
    """Return a readable navigational status, or ``None`` if unknown or undefined."""
    return None if code is None else _NAV_STATUS.get(code)


def describe(static: StaticData | None, nav_status: int | None) -> str:
    """Build the track description: ship type, size, destination, status, call sign."""
    parts: list[str] = []
    if static is not None:
        kind = ship_type_name(static.ship_type)
        if kind:
            parts.append(kind)
        if static.length_m and static.beam_m:
            parts.append(f"{static.length_m} m x {static.beam_m} m")
        elif static.length_m:
            parts.append(f"{static.length_m} m")
        if static.destination:
            parts.append(f"destination {static.destination}")
    status = nav_status_name(nav_status)
    if status:
        parts.append(status)
    if static is not None and static.callsign:
        parts.append(f"call sign {static.callsign}")
    return "; ".join(parts)


def _whole(value: object) -> int | None:
    """Return ``value`` as an int if it is a whole number, else ``None``."""
    real = number(value)
    return int(real) if real is not None and real == int(real) else None


def _size(dimension: object) -> tuple[int | None, int | None]:
    """Return ``(length, beam)`` in metres from an AIS dimension block."""
    if not isinstance(dimension, dict):
        return None, None
    bow, stern, port, starboard = (_whole(dimension.get(key)) or 0 for key in "ABCD")
    return (bow + stern) or None, (port + starboard) or None


def _valid_part(part: object) -> dict[str, Any]:
    """Return a StaticDataReport part if it is present and marked valid, else ``{}``."""
    return part if isinstance(part, dict) and part.get("Valid") is True else {}


def merge_static(
    previous: StaticData | None, kind: str, body: dict[str, Any], now: datetime
) -> StaticData:
    """Merge one static message into what is already known about a vessel.

    Empty fields in the new message never erase known values: a class B vessel
    sends its name and its other details in separate parts.
    """
    merged = replace(previous, updated_at=now) if previous else StaticData(updated_at=now)
    if kind == "ShipStaticData":
        sources = [body]
        name, destination = clean_text(body.get("Name")), clean_text(body.get("Destination"))
    else:
        # StaticDataReport: part A carries the name, part B the other details.
        report_a, report_b = _valid_part(body.get("ReportA")), _valid_part(body.get("ReportB"))
        name, destination = clean_text(report_a.get("Name")), ""
        sources = [report_b] if report_b else []

    if name:
        merged = replace(merged, name=name)
    if destination:
        merged = replace(merged, destination=destination)
    for source in sources:
        callsign = clean_text(source.get("CallSign"))
        ship_type = _whole(source.get("Type", source.get("ShipType")))
        length, beam = _size(source.get("Dimension"))
        merged = replace(
            merged,
            callsign=callsign or merged.callsign,
            ship_type=ship_type or merged.ship_type,
            length_m=length or merged.length_m,
            beam_m=beam or merged.beam_m,
        )
    return merged


# --- the stateful cleaner ---


class AisCleaner:
    """Applies the AIS rules to a stream of AISStream messages."""

    def __init__(self, rules: AisRules) -> None:
        """Create a cleaner with empty memory."""
        self.rules = rules
        self.counts: Counter[str] = Counter()
        self._static: dict[int, StaticData] = {}
        self._last: dict[int, Fix] = {}

    def clean(self, message: dict[str, Any], now: datetime) -> Track | None:
        """Clean one message.

        Args:
            message: A parsed AISStream message.
            now: The time the message arrived (UTC).

        Returns:
            A track for a position message that passes every rule. ``None`` for
            a dropped message and for static data, which is cached instead.
        """
        outcome = self._apply(message, now)
        if isinstance(outcome, Track):
            self.counts[KEPT] += 1
            return outcome
        self.counts[outcome] += 1
        return None

    def _apply(  # noqa: PLR0911 - one return per rule
        self, message: dict[str, Any], now: datetime
    ) -> Track | str:
        """Return the cleaned track, or the name of the reason it was not kept."""
        kind = message.get("MessageType")
        if kind not in POSITION_TYPES and kind not in STATIC_TYPES:
            return UNSUPPORTED
        container, meta = message.get("Message"), message.get("MetaData")
        body = container.get(kind) if isinstance(container, dict) else None
        if not isinstance(body, dict):
            return MALFORMED
        meta = meta if isinstance(meta, dict) else {}
        mmsi = _whole(body.get("UserID", meta.get("MMSI")))
        if mmsi is None:
            return MALFORMED

        if kind in STATIC_TYPES:
            return self._cache_static(mmsi, str(kind), body, now)

        latitude, longitude = number(body.get("Latitude")), number(body.get("Longitude"))
        if (
            latitude is None
            or longitude is None
            or not is_valid_position(body.get("Valid"), latitude, longitude)
        ):
            return INVALID_POSITION
        if not self.rules.aoi.contains(latitude, longitude):
            return OUTSIDE_AOI
        if not self.rules.allow_non_vessel_mmsi and not is_vessel_mmsi(mmsi):
            return MMSI_NOT_VESSEL

        at = parse_time_utc(meta.get("time_utc")) or now
        if is_stale(at, now, self.rules.max_age_seconds):
            return STALE
        fix, previous = Fix(latitude, longitude, at), self._last.get(mmsi)
        if is_duplicate(previous, fix):
            return DUPLICATE
        if previous is not None and is_position_jump(
            previous, fix, max_speed_kn=self.rules.max_speed_kn, slack_nm=self.rules.jump_slack_nm
        ):
            return POSITION_JUMP
        self._last[mmsi] = fix

        static = self._fresh_static(mmsi, now)
        course = clean_course(number(body.get("Cog")))
        name = (static.name if static else "") or clean_text(meta.get("ShipName"))
        return Track(
            source=Source.AIS,
            key=str(mmsi),
            name=display_name(name, mmsi),
            latitude=latitude,
            longitude=longitude,
            observed_at=at,
            speed_kn=clean_speed(number(body.get("Sog"))),
            course_deg=course,
            heading_deg=clean_heading(number(body.get("TrueHeading")), course),
            callsign=(static.callsign or None) if static else None,
            description=describe(static, _whole(body.get("NavigationalStatus"))),
        )

    def _cache_static(self, mmsi: int, kind: str, body: dict[str, Any], now: datetime) -> str:
        """Remember a vessel's static data. Returns the outcome name."""
        if body.get("Valid") is False:
            return INVALID_STATIC
        if not self.rules.allow_non_vessel_mmsi and not is_vessel_mmsi(mmsi):
            return MMSI_NOT_VESSEL
        self._static[mmsi] = merge_static(self._fresh_static(mmsi, now), kind, body, now)
        return STATIC_CACHED

    def _fresh_static(self, mmsi: int, now: datetime) -> StaticData | None:
        """Return cached static data for a vessel unless it has aged out."""
        static = self._static.get(mmsi)
        if static is None:
            return None
        if (now - static.updated_at).total_seconds() > self.rules.static_cache_seconds:
            del self._static[mmsi]
            return None
        return static

    def prune(self, now: datetime) -> int:
        """Forget vessels not heard from for a long time. Returns how many entries went."""
        old_fixes = [
            mmsi
            for mmsi, fix in self._last.items()
            if (now - fix.at).total_seconds() > LAST_FIX_TTL_SECONDS
        ]
        old_static = [
            mmsi
            for mmsi, static in self._static.items()
            if (now - static.updated_at).total_seconds() > self.rules.static_cache_seconds
        ]
        for mmsi in old_fixes:
            del self._last[mmsi]
        for mmsi in old_static:
            del self._static[mmsi]
        return len(old_fixes) + len(old_static)

    @property
    def tracked(self) -> int:
        """How many vessels have a remembered position."""
        return len(self._last)
