# SPDX-License-Identifier: Apache-2.0
"""Turn a cleaned ``Track`` into a Lattice track entity.

Every ship and aircraft is one ``TEMPLATE_TRACK`` entity with a fixed ID, so an
update replaces the earlier one instead of adding a duplicate. Lattice rejects
altitude referenced to mean sea level, so heights are always sent as height
above the WGS84 ellipsoid.
"""

from datetime import datetime, timedelta
from typing import Any, Final

from anduril import (
    Aliases,
    AlternateId,
    Enu,
    Indicators,
    Location,
    MilView,
    ModeS,
    Ontology,
    Position,
    Provenance,
    Quaternion,
    TransponderCodes,
)

from lattice_cop.geo import KNOTS_TO_MPS, heading_quaternion, velocity_enu
from lattice_cop.models import Source, Track

ENTITY_ID_PREFIX: Final = "lattice-cop"

_INTEGRATION: Final = {Source.AIS: "lattice-cop-ais", Source.ADSB: "lattice-cop-adsb"}
_DATA_TYPE: Final = {Source.AIS: "ais", Source.ADSB: "ads-b"}
_PLATFORM: Final = {Source.AIS: "Surface Vessel", Source.ADSB: "Airplane"}

MAX_MODE_S_ADDRESS: Final = 0xFFFFFE
"""Lattice expects a Mode S address between 1 and this value."""


def entity_id(track: Track) -> str:
    """Return the fixed entity ID: ``lattice-cop-ais-{MMSI}`` or ``lattice-cop-adsb-{hex}``."""
    return f"{ENTITY_ID_PREFIX}-{track.source.value}-{track.key}"


def _location(track: Track) -> Location:
    """Build position, velocity and heading for a track."""
    velocity = speed = attitude = None
    if track.speed_kn is not None:
        speed = track.speed_kn * KNOTS_TO_MPS
        if track.course_deg is not None:
            east, north, up = velocity_enu(
                track.speed_kn, track.course_deg, track.vertical_rate_fpm
            )
            velocity = Enu(e=east, n=north, u=up)
    if track.heading_deg is not None:
        x, y, z, w = heading_quaternion(track.heading_deg)
        attitude = Quaternion(x=x, y=y, z=z, w=w)
    return Location(
        position=Position(
            latitude_degrees=track.latitude,
            longitude_degrees=track.longitude,
            altitude_hae_meters=track.altitude_hae_m,
        ),
        velocity_enu=velocity,
        speed_mps=speed,
        attitude_enu=attitude,
    )


def _alternate_ids(track: Track) -> list[AlternateId] | None:
    """List the other identifiers a track is known by.

    The SDK has no alternate-ID type for an ICAO address; that goes in the
    transponder codes instead.
    """
    ids = [
        AlternateId(id=value, type=kind)
        for value, kind in (
            (track.key if track.source is Source.AIS else None, "ALT_ID_TYPE_MMSI_ID"),
            (track.callsign, "ALT_ID_TYPE_CALLSIGN"),
            (track.registration, "ALT_ID_TYPE_REGISTRATION_ID"),
        )
        if value
    ]
    return ids or None


def mode_s_address(key: str) -> int | None:
    """Return an ICAO hex address as a number, or ``None`` if it is not a real one."""
    try:
        address = int(key, 16)
    except ValueError:
        # readsb marks non-ICAO addresses (such as TIS-B track files) with "~".
        return None
    return address if 1 <= address <= MAX_MODE_S_ADDRESS else None


def _transponder_codes(track: Track) -> TransponderCodes:
    """Build an aircraft's Mode S address and flight ID, squawk and pressure altitude."""
    altitude = track.pressure_altitude_ft
    return TransponderCodes(
        # The squawk is sent as it is read aloud: 7700 goes out as the number 7700.
        mode3=int(track.squawk) if track.squawk else None,
        mode_s=ModeS(id=track.callsign, address=mode_s_address(track.key)),
        mode_c_altitude_ft=None if altitude is None else round(altitude),
    )


def track_to_entity(
    track: Track, *, created_time: datetime, now: datetime, expiry_seconds: float
) -> dict[str, Any]:
    """Build the keyword arguments for ``publish_entity``.

    Args:
        track: The cleaned report.
        created_time: When this process first saw the vessel or aircraft.
        now: The publish time. Expiry is counted from here, not from the
            message time, so a late message never carries an expiry in the past.
        expiry_seconds: How long the track stays live without another update.
    """
    is_vessel = track.source is Source.AIS
    entity: dict[str, Any] = {
        "entity_id": entity_id(track),
        "is_live": True,
        "created_time": created_time,
        "expiry_time": now + timedelta(seconds=expiry_seconds),
        "aliases": Aliases(name=track.name, alternate_ids=_alternate_ids(track)),
        "mil_view": MilView(
            disposition="DISPOSITION_NEUTRAL",
            environment="ENVIRONMENT_SURFACE" if is_vessel else "ENVIRONMENT_AIR",
        ),
        "location": _location(track),
        "ontology": Ontology(
            template="TEMPLATE_TRACK",
            platform_type=_PLATFORM[track.source],
            specific_type=track.specific_type,
        ),
        "provenance": Provenance(
            integration_name=_INTEGRATION[track.source],
            data_type=_DATA_TYPE[track.source],
            source_update_time=track.observed_at,
        ),
    }
    if track.description:
        entity["description"] = track.description
    if not is_vessel:
        entity["transponder_codes"] = _transponder_codes(track)
        # Always sent, so the flag clears again when the emergency ends.
        entity["indicators"] = Indicators(emergency=track.emergency)
    return entity
