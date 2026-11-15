# SPDX-License-Identifier: Apache-2.0
"""ADS-B cleaning rules. Every aircraft is synthetic."""

import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from lattice_cop.clean import adsb
from lattice_cop.config import load_settings
from lattice_cop.geo import BoundingBox
from lattice_cop.models import Source, Track
from lattice_cop.sources.readsb import Aircraft, Snapshot, parse_snapshot
from tests.builders import aircraft_entry

AOI = BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)
CENTER = (27.9755, -82.5332)
NOW = 1_767_268_800.0  # 2026-01-01T12:00:00Z
GEOID = -26.7


def cleaner(**overrides: Any) -> adsb.AdsbCleaner:
    return adsb.AdsbCleaner(adsb.AdsbRules(**{"aoi": AOI, "center": CENTER, **overrides}))


def plane(**fields: Any) -> Aircraft:
    defaults: dict[str, Any] = {
        "hex": "ffff01",
        "latitude": 27.75,
        "longitude": -82.55,
        "seen_pos": 0.5,
    }
    return Aircraft(**{**defaults, **fields})


def keep(target: adsb.AdsbCleaner, aircraft: Aircraft, now: float = NOW) -> Track:
    track = target.clean(aircraft, now)
    assert track is not None, dict(target.counts)
    return track


# --- pure rules ---


@pytest.mark.parametrize(
    ("aircraft", "height", "note"),
    [
        (plane(alt_geom_ft=35000, alt_baro_ft=34000), 10668.0, None),
        (plane(alt_geom_ft=0, on_ground=True), 0.0, None),
        (plane(alt_baro_ft=3000), 914.4 + GEOID, "altitude approximate"),
        (plane(on_ground=True), GEOID, "on ground"),
        (plane(), GEOID, "altitude unknown"),
    ],
)
def test_height_above_ellipsoid(aircraft: Aircraft, height: float, note: str | None) -> None:
    measured, remark = adsb.height_above_ellipsoid(aircraft, GEOID)
    assert measured == pytest.approx(height)
    assert remark == note


@pytest.mark.parametrize(
    ("aircraft", "name"),
    [
        (plane(flight="SYN101  ", registration="SYN-REG1"), "SYN101"),
        (plane(flight="        ", registration=" SYN-REG1 "), "SYN-REG1"),
        (plane(flight=None, registration=None), "ffff01"),
        (plane(flight="", registration=""), "ffff01"),
    ],
)
def test_display_name_prefers_callsign_then_registration_then_hex(
    aircraft: Aircraft, name: str
) -> None:
    assert adsb.display_name(aircraft) == name


@pytest.mark.parametrize(
    ("squawk", "meaning"),
    [
        ("7500", "unlawful interference"),
        ("7600", "radio failure"),
        (" 7700 ", "general emergency"),
        ("1200", None),
        ("", None),
        (None, None),
    ],
)
def test_emergency_squawks(squawk: str | None, meaning: str | None) -> None:
    assert adsb.emergency_meaning(squawk) == meaning


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 0.0), (359.9, 359.9), (360.0, 0.0), (361.0, None), (-1.0, None), (None, None)],
)
def test_angle_rule(value: float | None, expected: float | None) -> None:
    assert adsb.clean_angle(value) == expected


def test_ground_speed_rule() -> None:
    assert adsb.clean_ground_speed(0.0) == 0.0
    assert adsb.clean_ground_speed(450.5) == 450.5
    assert adsb.clean_ground_speed(-1.0) is None
    assert adsb.clean_ground_speed(None) is None


def test_describe_lists_type_registration_squawk_and_flags() -> None:
    aircraft = plane(type_code="B739", registration="SYN-REG1", squawk="7700")
    assert adsb.describe(aircraft, "altitude approximate") == (
        "B739; registration SYN-REG1; squawk 7700; EMERGENCY: general emergency; "
        "altitude approximate"
    )
    assert adsb.describe(plane(squawk="1200"), None) == "squawk 1200"
    assert adsb.describe(plane(), "on ground") == "on ground"
    assert adsb.describe(plane(), None) == ""


def test_rules_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "LATTICE_URL": "lattice-test.invalid",
        "LATTICE_SANDBOXES_TOKEN": "fake",
        "LATTICE_ENVIRONMENT_TOKEN": "fake",
        "ADSB_RADIUS_NM": "40",
        "ADSB_MAX_POSITION_AGE_SECONDS": "10",
        "ADSB_MAX_SPEED_KN": "800",
        "ADSB_ALLOW_NON_ICAO": "true",
        "POSITION_JUMP_SLACK_NM": "0.2",
        "GEOID_OFFSET_M": "-25",
    }.items():
        monkeypatch.setenv(name, value)
    assert adsb.AdsbRules.from_settings(load_settings(env_file=None)) == adsb.AdsbRules(
        aoi=AOI,
        center=CENTER,
        radius_nm=40,
        max_position_age_seconds=10,
        max_speed_kn=800,
        jump_slack_nm=0.2,
        allow_non_icao=True,
        geoid_offset_m=-25,
    )


# --- the cleaner ---


def test_a_good_aircraft_becomes_a_track() -> None:
    target = cleaner()
    track = keep(
        target,
        plane(
            flight="SYN101  ",
            registration="SYN-REG1",
            type_code="B739",
            alt_geom_ft=35000,
            ground_speed_kn=462.0,
            track_deg=91.5,
            true_heading_deg=93.0,
            geom_rate_fpm=-640.0,
            baro_rate_fpm=-600.0,
            squawk="6005",
        ),
    )

    assert track == Track(
        source=Source.ADSB,
        key="ffff01",
        name="SYN101",
        latitude=27.75,
        longitude=-82.55,
        observed_at=datetime.fromtimestamp(NOW - 0.5, tz=UTC),
        altitude_hae_m=pytest.approx(10668.0),
        speed_kn=462.0,
        course_deg=91.5,
        heading_deg=93.0,
        vertical_rate_fpm=-640.0,
        callsign="SYN101",
        registration="SYN-REG1",
        description="B739; registration SYN-REG1; squawk 6005",
    )
    assert target.counts == {"kept": 1}
    assert target.tracked == 1


def test_missing_speed_track_and_names_are_left_empty() -> None:
    track = keep(cleaner(), plane(alt_baro_ft=3000, baro_rate_fpm=500.0))
    assert track.name == "ffff01"
    assert track.speed_kn is None
    assert track.course_deg is None
    assert track.heading_deg is None
    assert track.vertical_rate_fpm == 500.0
    assert track.callsign is None
    assert track.registration is None
    assert track.altitude_hae_m == pytest.approx(914.4 + GEOID)
    assert track.description == "altitude approximate"


def test_heading_falls_back_to_track() -> None:
    assert keep(cleaner(), plane(track_deg=270.0)).heading_deg == 270.0


def test_an_aircraft_on_the_ground_sits_at_the_geoid_offset() -> None:
    track = keep(cleaner(), plane(on_ground=True, ground_speed_kn=12.0))
    assert track.altitude_hae_m == GEOID
    assert track.description == "on ground"


@pytest.mark.parametrize(
    ("aircraft", "reason"),
    [
        (plane(latitude=None, longitude=None), "no_position"),
        (plane(longitude=None), "no_position"),
        (plane(seen_pos=None), "no_position"),
        (plane(seen_pos=15.1), "stale"),
        (plane(latitude=29.5, longitude=-82.5), "outside_aoi"),
        (plane(hex="~ffff05"), "non_icao"),
    ],
)
def test_drops_are_counted_by_reason(aircraft: Aircraft, reason: str) -> None:
    target = cleaner()
    assert target.clean(aircraft, NOW) is None
    assert target.counts == {reason: 1}


def test_position_exactly_at_the_age_limit_is_kept() -> None:
    assert keep(cleaner(), plane(seen_pos=15.0)).key == "ffff01"


def test_inside_the_box_but_outside_the_radius_is_dropped() -> None:
    target = cleaner(radius_nm=20)
    assert target.clean(plane(latitude=27.45, longitude=-82.95), NOW) is None
    assert target.counts == {"outside_radius": 1}
    assert keep(target, plane(latitude=27.95, longitude=-82.55)).key == "ffff01"


def test_non_icao_addresses_can_be_allowed() -> None:
    assert keep(cleaner(allow_non_icao=True), plane(hex="~ffff05")).key == "~ffff05"


def test_impossible_move_is_a_position_jump() -> None:
    target = cleaner()
    keep(target, plane())
    # About 21 nm in one second.
    assert target.clean(plane(latitude=28.10, longitude=-82.55), NOW + 1) is None
    # 0.3 nm in two seconds is 540 kn: fine.
    keep(target, plane(latitude=27.755, longitude=-82.55), NOW + 2)
    assert target.counts == {"kept": 2, "position_jump": 1}


def test_an_unchanged_position_between_polls_is_kept_again() -> None:
    target = cleaner()
    keep(target, plane(seen_pos=0.5))
    keep(target, plane(seen_pos=1.5), NOW + 1)
    assert target.counts == {"kept": 2}


def test_emergency_squawk_is_kept_flagged_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="lattice_cop.clean.adsb")
    target = cleaner()

    first = keep(target, plane(squawk="7700"))
    keep(target, plane(squawk="7700"), NOW + 1)
    assert "EMERGENCY: general emergency" in first.description
    assert target.counts == {"kept": 2, "emergency_squawk": 1}
    assert len(caplog.records) == 1
    assert caplog.records[0].squawk == "7700"
    assert caplog.records[0].hex == "ffff01"

    # A different code, or the same code after a normal one, is a new event.
    keep(target, plane(squawk="7600"), NOW + 2)
    keep(target, plane(squawk="1200"), NOW + 3)
    keep(target, plane(squawk="7600"), NOW + 4)
    assert target.counts["emergency_squawk"] == 3
    assert len(caplog.records) == 3


def test_clean_snapshot_returns_only_the_kept_tracks() -> None:
    snapshot = Snapshot(
        now=NOW,
        messages=100,
        aircraft=(plane(), plane(hex="ffff02", latitude=None), plane(hex="ffff03", seen_pos=40.0)),
    )
    target = cleaner()
    assert [track.key for track in target.clean_snapshot(snapshot)] == ["ffff01"]
    assert target.counts == {"kept": 1, "no_position": 1, "stale": 1}


def test_prune_forgets_aircraft_that_went_quiet() -> None:
    target = cleaner()
    keep(target, plane(hex="ffff01", squawk="7700"))
    keep(target, plane(hex="ffff02"), NOW + 500)

    assert target.prune(NOW + 500) == 0
    assert target.prune(NOW + 700) == 1
    assert target.tracked == 1
    # The forgotten aircraft's emergency is announced again if it comes back.
    keep(target, plane(hex="ffff01", squawk="7700"), NOW + 701)
    assert target.counts["emergency_squawk"] == 2


def test_parsed_readsb_entries_flow_through_the_cleaner() -> None:
    snapshot = parse_snapshot(
        {
            "now": NOW,
            "messages": 10,
            "aircraft": [
                aircraft_entry(
                    "FFFF01",
                    flight="SYN101  ",
                    r="SYN-REG1",
                    t="B739",
                    alt_baro="ground",
                    gs=14.2,
                    track=181.0,
                    true_heading=180.0,
                    geom_rate=0,
                    baro_rate=64,
                    squawk="1200",
                )
            ],
        }
    )
    (track,) = cleaner().clean_snapshot(snapshot)
    assert track.name == "SYN101"
    assert track.registration == "SYN-REG1"
    assert track.altitude_hae_m == GEOID
    assert track.speed_kn == 14.2
    assert track.heading_deg == 180.0
    assert track.vertical_rate_fpm == 0.0
    assert track.description == "B739; registration SYN-REG1; squawk 1200; on ground"
