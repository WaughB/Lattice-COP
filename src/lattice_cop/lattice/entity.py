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
    Location,
    MilView,
    Ontology,
    Position,
    Provenance,
    Quaternion,
)

from lattice_cop.geo import KNOTS_TO_MPS, heading_quaternion, velocity_enu
from lattice_cop.models import Source, Track

ENTITY_ID_PREFIX: Final = "lattice-cop"

_INTEGRATION: Final = {Source.AIS: "lattice-cop-ais", Source.ADSB: "lattice-cop-adsb"}
_DATA_TYPE: Final = {Source.AIS: "ais", Source.ADSB: "ads-b"}
_PLATFORM: Final = {Source.AIS: "Surface Vessel", Source.ADSB: "Airplane"}


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
    alternate_ids = [AlternateId(id=track.key, type="ALT_ID_TYPE_MMSI_ID")] if is_vessel else None
    entity: dict[str, Any] = {
        "entity_id": entity_id(track),
        "is_live": True,
        "created_time": created_time,
        "expiry_time": now + timedelta(seconds=expiry_seconds),
        "aliases": Aliases(name=track.name, alternate_ids=alternate_ids),
        "mil_view": MilView(
            disposition="DISPOSITION_NEUTRAL",
            environment="ENVIRONMENT_SURFACE" if is_vessel else "ENVIRONMENT_AIR",
        ),
        "location": _location(track),
        "ontology": Ontology(template="TEMPLATE_TRACK", platform_type=_PLATFORM[track.source]),
        "provenance": Provenance(
            integration_name=_INTEGRATION[track.source],
            data_type=_DATA_TYPE[track.source],
            source_update_time=track.observed_at,
        ),
    }
    if track.description:
        entity["description"] = track.description
    return entity
