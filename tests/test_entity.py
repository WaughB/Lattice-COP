# SPDX-License-Identifier: Apache-2.0
"""Track to Lattice entity mapping. Every vessel and aircraft is synthetic."""

from datetime import timedelta

import pytest

from lattice_cop.lattice.entity import entity_id, track_to_entity
from lattice_cop.models import Source, Track
from tests.builders import T0, after

VESSEL = Track(
    source=Source.AIS,
    key="999000001",
    name="SYNTHETIC ONE",
    latitude=27.75,
    longitude=-82.55,
    observed_at=T0,
    speed_kn=10.0,
    course_deg=90.0,
    heading_deg=0.0,
    callsign="SYN1",
    description="Cargo; 190 m x 32 m",
)
AIRCRAFT = Track(
    source=Source.ADSB,
    key="ffff01",
    name="SYN101",
    latitude=27.90,
    longitude=-82.40,
    observed_at=T0,
    altitude_hae_m=10668.0,
    speed_kn=450.0,
    course_deg=180.0,
    heading_deg=182.0,
    vertical_rate_fpm=-640.0,
)


def test_entity_ids_are_fixed_per_vessel_and_aircraft() -> None:
    assert entity_id(VESSEL) == "lattice-cop-ais-999000001"
    assert entity_id(AIRCRAFT) == "lattice-cop-adsb-ffff01"


def test_vessel_mapping() -> None:
    entity = track_to_entity(VESSEL, created_time=T0, now=after(30), expiry_seconds=600)

    assert entity["entity_id"] == "lattice-cop-ais-999000001"
    assert entity["is_live"] is True
    assert entity["created_time"] == T0
    # Expiry counts from the publish time, not the message time.
    assert entity["expiry_time"] == after(30) + timedelta(seconds=600)
    assert entity["description"] == "Cargo; 190 m x 32 m"
    assert entity["aliases"].name == "SYNTHETIC ONE"
    assert [(alt.id, alt.type) for alt in entity["aliases"].alternate_ids] == [
        ("999000001", "ALT_ID_TYPE_MMSI_ID")
    ]
    assert entity["ontology"].template == "TEMPLATE_TRACK"
    assert entity["ontology"].platform_type == "Surface Vessel"
    assert entity["mil_view"].environment == "ENVIRONMENT_SURFACE"
    assert entity["mil_view"].disposition == "DISPOSITION_NEUTRAL"
    assert entity["provenance"].integration_name == "lattice-cop-ais"
    assert entity["provenance"].data_type == "ais"
    assert entity["provenance"].source_update_time == T0

    location = entity["location"]
    assert location.position.latitude_degrees == 27.75
    assert location.position.longitude_degrees == -82.55
    assert location.position.altitude_hae_meters == 0.0
    assert location.speed_mps == pytest.approx(5.14444)
    assert location.velocity_enu.e == pytest.approx(5.14444)
    assert location.velocity_enu.n == pytest.approx(0.0, abs=1e-9)
    assert location.velocity_enu.u == 0.0
    # Heading north: a quarter turn anticlockwise from east.
    assert location.attitude_enu.z == pytest.approx(0.7071068)
    assert location.attitude_enu.w == pytest.approx(0.7071068)
    assert (location.attitude_enu.x, location.attitude_enu.y) == (0.0, 0.0)


def test_aircraft_mapping() -> None:
    entity = track_to_entity(AIRCRAFT, created_time=T0, now=T0, expiry_seconds=60)

    assert entity["entity_id"] == "lattice-cop-adsb-ffff01"
    assert entity["expiry_time"] == after(60)
    assert "description" not in entity
    assert entity["aliases"].name == "SYN101"
    # The SDK has no alternate-ID type for an ICAO address, so none is sent.
    assert entity["aliases"].alternate_ids is None
    assert entity["ontology"].platform_type == "Airplane"
    assert entity["mil_view"].environment == "ENVIRONMENT_AIR"
    assert entity["provenance"].integration_name == "lattice-cop-adsb"
    assert entity["provenance"].data_type == "ads-b"

    location = entity["location"]
    assert location.position.altitude_hae_meters == 10668.0
    assert location.speed_mps == pytest.approx(231.4998)
    assert location.velocity_enu.e == pytest.approx(0.0, abs=1e-9)
    assert location.velocity_enu.n == pytest.approx(-231.4998)
    assert location.velocity_enu.u == pytest.approx(-3.2512)


def test_unknown_speed_course_and_heading_are_left_out() -> None:
    bare = Track(Source.AIS, "999000005", "MMSI 999000005", 27.8, -82.7, T0)
    location = track_to_entity(bare, created_time=T0, now=T0, expiry_seconds=600)["location"]
    assert location.velocity_enu is None
    assert location.speed_mps is None
    assert location.attitude_enu is None

    drifting = Track(Source.AIS, "999000005", "X", 27.8, -82.7, T0, speed_kn=2.0)
    location = track_to_entity(drifting, created_time=T0, now=T0, expiry_seconds=600)["location"]
    assert location.speed_mps == pytest.approx(1.028888)
    assert location.velocity_enu is None
