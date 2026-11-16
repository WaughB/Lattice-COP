# SPDX-License-Identifier: Apache-2.0
"""AIS cleaning rules. Every vessel is synthetic."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tampa_cop.clean import ais
from tampa_cop.clean.common import Fix
from tampa_cop.config import load_settings
from tampa_cop.geo import BoundingBox
from tampa_cop.models import Source, Track
from tests.builders import (
    IN_AOI,
    T0,
    after,
    ais_position,
    ais_ship_static,
    ais_static_report,
    time_utc,
)

AOI = BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)
# Synthetic MMSIs start with 9, which the vessel rule drops, so most tests allow them.
RULES = ais.AisRules(aoi=AOI, allow_non_vessel_mmsi=True)


def cleaner(**overrides: Any) -> ais.AisCleaner:
    return ais.AisCleaner(ais.AisRules(**{"aoi": AOI, "allow_non_vessel_mmsi": True, **overrides}))


def keep(target: ais.AisCleaner, message: dict[str, Any], now: datetime = T0) -> Track:
    track = target.clean(message, now)
    assert track is not None, dict(target.counts)
    return track


# --- pure rules ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-01-01 12:00:00.123456789 +0000 UTC", datetime(2026, 1, 1, 12, 0, 0, 123456, UTC)),
        ("2026-01-01 12:00:00.5 +0000 UTC", datetime(2026, 1, 1, 12, 0, 0, 500000, UTC)),
        ("2026-01-01 12:00:00 +0000 UTC", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)),
        ("2026-01-01 14:00:00.25 +0200", datetime(2026, 1, 1, 12, 0, 0, 250000, UTC)),
        ("2026-01-01 12:00:00", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)),
    ],
)
def test_parse_time_utc_reads_aisstream_times(text: str, expected: datetime) -> None:
    assert ais.parse_time_utc(text) == expected


@pytest.mark.parametrize("value", [None, 1767268800, "", "2026-01-01", "not a time", "x y z"])
def test_parse_time_utc_rejects_anything_else(value: object) -> None:
    assert ais.parse_time_utc(value) is None


@pytest.mark.parametrize(
    ("valid", "latitude", "longitude", "usable"),
    [
        (True, 27.75, -82.55, True),
        (None, 27.75, -82.55, True),
        (False, 27.75, -82.55, False),
        (True, 91.0, -82.55, False),
        (True, 27.75, 181.0, False),
        (True, 91.0, 181.0, False),
        (True, -90.0, 180.0, True),
        (True, -90.5, 0.0, False),
    ],
)
def test_valid_position_rule(
    valid: object, latitude: float, longitude: float, usable: bool
) -> None:
    assert ais.is_valid_position(valid, latitude, longitude) is usable


@pytest.mark.parametrize(
    ("mmsi", "vessel"),
    [
        (200000001, True),
        (799999999, True),
        (99900001, False),  # eight digits
        (3660001, False),  # coast station (leading zeros lost)
        (111000001, False),  # search-and-rescue aircraft
        (800000001, False),  # handheld radio
        (970000001, False),  # search-and-rescue transponder
        (992000001, False),  # aid to navigation
        (999000001, False),  # the synthetic range used in tests
        (2000000010, False),  # ten digits
    ],
)
def test_vessel_mmsi_rule(mmsi: int, vessel: bool) -> None:
    assert ais.is_vessel_mmsi(mmsi) is vessel


@pytest.mark.parametrize(("age", "stale"), [(0, False), (300, False), (300.5, True), (-30, False)])
def test_stale_rule(age: float, stale: bool) -> None:
    assert ais.is_stale(T0 - timedelta(seconds=age), T0, 300.0) is stale


def test_duplicate_rule_needs_the_same_place_and_time() -> None:
    fix = Fix(27.75, -82.55, T0)
    assert ais.is_duplicate(fix, Fix(27.75, -82.55, T0)) is True
    assert ais.is_duplicate(fix, Fix(27.75, -82.55, after(1))) is False
    assert ais.is_duplicate(fix, Fix(27.76, -82.55, T0)) is False
    assert ais.is_duplicate(None, fix) is False


@pytest.mark.parametrize(
    ("sog", "expected"),
    [(0.0, 0.0), (12.4, 12.4), (102.2, 102.2), (102.3, None), (None, None), (-1.0, None)],
)
def test_speed_rule(sog: float | None, expected: float | None) -> None:
    assert ais.clean_speed(sog) == expected


@pytest.mark.parametrize(
    ("cog", "expected"), [(0.0, 0.0), (359.9, 359.9), (360.0, None), (None, None), (-5.0, None)]
)
def test_course_rule(cog: float | None, expected: float | None) -> None:
    assert ais.clean_course(cog) == expected


@pytest.mark.parametrize(
    ("heading", "course", "expected"),
    [
        (87.0, 90.0, 87.0),
        (0.0, 90.0, 0.0),
        (511.0, 90.0, 90.0),
        (511.0, None, None),
        (None, 45.0, 45.0),
    ],
)
def test_heading_rule_falls_back_to_course(
    heading: float | None, course: float | None, expected: float | None
) -> None:
    assert ais.clean_heading(heading, course) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SYNTHETIC ONE@@@@@@@", "SYNTHETIC ONE"),
        ("SYNTHETIC ONE       ", "SYNTHETIC ONE"),
        ("  SYN 1 @ @@", "SYN 1"),
        ("@@@@@@@@", ""),
        ("", ""),
        (None, ""),
        (42, ""),
    ],
)
def test_text_rule_trims_padding(raw: object, expected: str) -> None:
    assert ais.clean_text(raw) == expected


def test_display_name_falls_back_to_the_mmsi() -> None:
    assert ais.display_name("SYNTHETIC ONE", 999000001) == "SYNTHETIC ONE"
    assert ais.display_name("", 999000001) == "MMSI 999000001"


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (30, "Fishing"),
        (37, "Pleasure craft"),
        (52, "Tug"),
        (60, "Passenger"),
        (69, "Passenger"),
        (70, "Cargo"),
        (84, "Tanker"),
        (99, "Other type"),
        (0, None),
        (10, None),
        (57, None),
        (None, None),
    ],
)
def test_ship_type_names(code: int | None, name: str | None) -> None:
    assert ais.ship_type_name(code) == name


def test_nav_status_names() -> None:
    assert ais.nav_status_name(0) == "under way using engine"
    assert ais.nav_status_name(5) == "moored"
    assert ais.nav_status_name(15) is None
    assert ais.nav_status_name(None) is None


def test_describe_joins_what_is_known() -> None:
    full = ais.StaticData(T0, "SYNTHETIC ONE", "SYN1", 70, 190, 32, "SYNTHETIC PORT")
    assert ais.describe(full, 0) == (
        "Cargo; 190 m x 32 m; destination SYNTHETIC PORT; under way using engine; call sign SYN1"
    )
    assert ais.describe(ais.StaticData(T0, length_m=12), None) == "12 m"
    assert ais.describe(ais.StaticData(T0, beam_m=4), 1) == "at anchor"
    assert ais.describe(None, 5) == "moored"
    assert ais.describe(None, None) == ""


def test_rules_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "LATTICE_URL": "lattice-test.invalid",
        "LATTICE_SANDBOXES_TOKEN": "fake",
        "LATTICE_ENVIRONMENT_TOKEN": "fake",
        "AIS_MAX_AGE_SECONDS": "120",
        "AIS_MAX_SPEED_KN": "40",
        "AIS_ALLOW_NON_VESSEL_MMSI": "true",
        "AIS_STATIC_CACHE_SECONDS": "60",
        "POSITION_JUMP_SLACK_NM": "0.3",
    }.items():
        monkeypatch.setenv(name, value)
    assert ais.AisRules.from_settings(load_settings(env_file=None)) == ais.AisRules(
        aoi=AOI,
        max_age_seconds=120,
        max_speed_kn=40,
        jump_slack_nm=0.3,
        allow_non_vessel_mmsi=True,
        static_cache_seconds=60,
    )


# --- the cleaner ---


def test_a_good_position_becomes_a_track() -> None:
    target = cleaner()
    track = keep(target, ais_position(ship_name="SYNTHETIC ONE   "))

    assert track == Track(
        source=Source.AIS,
        key="999000001",
        name="SYNTHETIC ONE",
        latitude=27.75,
        longitude=-82.55,
        observed_at=T0,
        speed_kn=8.2,
        course_deg=91.0,
        heading_deg=90.0,
        description="under way using engine",
    )
    assert target.counts == {"kept": 1}
    assert target.tracked == 1


def test_class_b_position_with_nothing_available_keeps_only_the_position() -> None:
    track = keep(
        cleaner(),
        ais_position(
            999000005, kind="StandardClassBPositionReport", sog=102.3, cog=360, heading=511
        ),
    )
    assert track.name == "MMSI 999000005"
    assert track.speed_kn is None
    assert track.course_deg is None
    assert track.heading_deg is None
    assert track.description == ""


def test_heading_511_falls_back_to_the_course() -> None:
    assert keep(cleaner(), ais_position(heading=511, cog=123.4)).heading_deg == 123.4


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (ais_position(valid=False), "invalid_position"),
        (ais_position(point=(91.0, 181.0)), "invalid_position"),
        (ais_position(point=(27.75, 181.0)), "invalid_position"),
        (ais_position(point=(29.0, -82.5)), "outside_aoi"),
        (ais_position(at=after(-301)), "stale"),
        ({"MessageType": "AidsToNavigationReport", "Message": {}}, "unsupported"),
        ({"MessageType": None}, "unsupported"),
        ({"MessageType": "PositionReport"}, "malformed"),
        ({"MessageType": "PositionReport", "Message": {"PositionReport": []}}, "malformed"),
        ({"MessageType": "PositionReport", "Message": {"PositionReport": {}}}, "malformed"),
        (
            {"MessageType": "PositionReport", "Message": {"PositionReport": {"UserID": "x"}}},
            "malformed",
        ),
        (ais_ship_static(valid=False), "invalid_static"),
    ],
)
def test_drops_are_counted_by_reason(message: dict[str, Any], reason: str) -> None:
    target = cleaner()
    assert target.clean(message, T0) is None
    assert target.counts == {reason: 1}


def test_position_without_coordinates_is_invalid() -> None:
    message = ais_position()
    del message["Message"]["PositionReport"]["Latitude"]
    target = cleaner()
    assert target.clean(message, T0) is None
    assert target.counts == {"invalid_position": 1}


def test_non_vessel_mmsis_are_dropped_unless_allowed() -> None:
    strict = ais.AisCleaner(ais.AisRules(aoi=AOI))
    assert strict.clean(ais_position(992000001), T0) is None
    assert strict.clean(ais_ship_static(992000001), T0) is None
    assert strict.counts == {"mmsi_not_vessel": 2}
    assert keep(strict, ais_position(200000001)).key == "200000001"

    assert keep(cleaner(), ais_position(992000001)).key == "992000001"


def test_mmsi_falls_back_to_metadata() -> None:
    message = ais_position()
    del message["Message"]["PositionReport"]["UserID"]
    assert keep(cleaner(), message).key == "999000001"


def test_a_message_without_a_readable_time_uses_the_arrival_time() -> None:
    message = ais_position()
    message["MetaData"]["time_utc"] = "garbage"
    assert keep(cleaner(), message, now=after(7)).observed_at == after(7)

    del message["MetaData"]
    assert keep(cleaner(), message, now=after(9)).observed_at == after(9)


def test_exact_repeat_is_a_duplicate_and_a_later_copy_is_not() -> None:
    target = cleaner()
    keep(target, ais_position())
    assert target.clean(ais_position(), after(1)) is None
    keep(target, ais_position(at=after(2)), now=after(2))
    assert target.counts == {"kept": 2, "duplicate": 1}


def test_impossible_move_is_a_position_jump_and_does_not_replace_the_last_fix() -> None:
    target = cleaner()
    keep(target, ais_position())
    far = (28.10, -82.30)  # about 25 nm away
    assert target.clean(ais_position(point=far, at=after(10)), after(10)) is None
    # The vessel carries on from where it really was.
    keep(target, ais_position(point=(27.751, -82.55), at=after(20)), now=after(20))
    assert target.counts == {"kept": 2, "position_jump": 1}


def test_a_jump_heals_once_enough_time_has_passed() -> None:
    target = cleaner(max_age_seconds=7200)
    keep(target, ais_position())
    far = (28.10, -82.30)
    assert target.clean(ais_position(point=far, at=after(60)), after(60)) is None
    keep(target, ais_position(point=far, at=after(3600)), now=after(3600))


def test_static_data_is_cached_and_merged_into_the_next_position() -> None:
    target = cleaner()
    assert target.clean(ais_ship_static(), T0) is None
    track = keep(target, ais_position(at=after(5)), now=after(5))

    assert track.name == "SYNTHETIC ONE"
    assert track.callsign == "SYN1"
    assert track.description == (
        "Cargo; 190 m x 32 m; destination SYNTHETIC PORT; under way using engine; call sign SYN1"
    )
    assert target.counts == {"static_cached": 1, "kept": 1}


def test_class_b_static_parts_merge_without_erasing_each_other() -> None:
    target = cleaner()
    target.clean(ais_static_report(name="SYNTHETIC FIVE@@@"), T0)
    target.clean(ais_static_report(callsign="SYN5@@", ship_type=37), after(1))
    # A later part A with an empty name must not blank the name.
    target.clean(ais_static_report(name=""), after(2))

    track = keep(
        target, ais_position(999000005, kind="StandardClassBPositionReport", at=after(3)), after(3)
    )
    assert track.name == "SYNTHETIC FIVE"
    assert track.callsign == "SYN5"
    assert track.description == "Pleasure craft; 12 m x 4 m; call sign SYN5"


def test_static_data_tolerates_missing_and_odd_fields() -> None:
    target = cleaner()
    message = ais_ship_static(dimension=(0, 0, 0, 0), ship_type=0, callsign="", destination="@@")
    message["Message"]["ShipStaticData"]["Dimension"] = "none"
    target.clean(message, T0)
    report = ais_static_report(callsign="SYN1")
    del report["Message"]["StaticDataReport"]["ReportA"]
    report["Message"]["StaticDataReport"]["ReportB"]["Dimension"] = {"A": 30.5, "B": True}
    target.clean(report | {"MetaData": {"MMSI": 999000001}}, T0)

    track = keep(target, ais_position(nav_status=None))
    assert track.name == "SYNTHETIC ONE"
    assert track.description == ""


def test_metadata_name_is_used_until_static_data_arrives() -> None:
    target = cleaner()
    assert keep(target, ais_position(ship_name="META NAME@@")).name == "META NAME"
    target.clean(ais_ship_static(), after(1))
    assert keep(target, ais_position(ship_name="META NAME@@", at=after(2)), after(2)).name == (
        "SYNTHETIC ONE"
    )


def test_static_data_expires_after_the_cache_time() -> None:
    target = cleaner(static_cache_seconds=3600, max_age_seconds=1e9)
    target.clean(ais_ship_static(), T0)
    assert keep(target, ais_position(at=after(3600)), after(3600)).name == "SYNTHETIC ONE"
    assert keep(target, ais_position(at=after(3601)), after(3601)).name == "MMSI 999000001"


def test_prune_forgets_old_fixes_and_old_static_data() -> None:
    target = cleaner(static_cache_seconds=7200)
    target.clean(ais_ship_static(999000001), T0)
    keep(target, ais_position(999000001))
    target.clean(ais_ship_static(999000002), after(3000))
    keep(target, ais_position(999000002, at=after(3000)), after(3000))

    assert target.prune(after(3000)) == 0
    assert target.prune(after(3700)) == 1  # the first vessel's fix
    assert target.tracked == 1
    assert target.prune(after(7300)) == 2  # its static data, and the second fix
    assert target.tracked == 0
    assert target.prune(after(20000)) == 1


def test_metadata_position_is_not_trusted_over_the_message_body() -> None:
    message = ais_position(point=(29.0, -82.5))
    message["MetaData"]["latitude"], message["MetaData"]["longitude"] = IN_AOI
    target = cleaner()
    assert target.clean(message, T0) is None
    assert target.counts == {"outside_aoi": 1}


def test_time_format_helper_matches_what_the_parser_reads() -> None:
    assert ais.parse_time_utc(time_utc(after(1.5))) == after(1.5)
