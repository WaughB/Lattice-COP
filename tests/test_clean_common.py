# SPDX-License-Identifier: Apache-2.0
"""Rules shared by both cleaners, and the publish throttle."""

import pytest

from tampa_cop.clean.common import Fix, is_position_jump, number
from tampa_cop.clean.throttle import Throttle, should_publish
from tests.builders import T0, after


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3.0), (2.5, 2.5), (True, None), ("3", None), (None, None), ([1], None)],
)
def test_number_accepts_real_numbers_only(value: object, expected: float | None) -> None:
    assert number(value) == expected


@pytest.mark.parametrize(
    ("seconds", "north_nm", "jump"),
    [
        (60, 0.5, False),  # 30 kn
        (60, 0.9, False),  # 54 kn, inside the 0.1 nm slack
        (60, 1.0, True),  # 60 kn
        (3600, 49.0, False),
        (3600, 51.0, True),
        (0, 0.05, False),  # same instant, within the slack
        (0, 0.5, True),  # same instant, far apart
        (-60, 1.0, True),  # out of order is judged the same way
        (-60, 0.5, False),
    ],
)
def test_position_jump_compares_distance_with_top_speed(
    seconds: float, north_nm: float, jump: bool
) -> None:
    previous = Fix(27.50, -82.55, T0)
    current = Fix(27.50 + north_nm / 60.04, -82.55, after(seconds))
    assert is_position_jump(previous, current, max_speed_kn=50, slack_nm=0.1) is jump


@pytest.mark.parametrize(
    ("last_time", "last_print", "now", "new_print", "allowed"),
    [
        (None, None, 100.0, "a", True),
        (100.0, "a", 105.0, "a", False),
        (100.0, "a", 110.0, "a", True),
        (100.0, "a", 101.0, "b", True),
    ],
)
def test_should_publish(
    last_time: float | None, last_print: object, now: float, new_print: object, allowed: bool
) -> None:
    assert should_publish(last_time, last_print, now, new_print, 10.0) is allowed


def test_throttle_limits_each_track_separately_and_lets_changes_through() -> None:
    throttle = Throttle(10.0)

    assert throttle.allow("999000001", 0.0, ("NAME", "")) is True
    assert throttle.allow("999000001", 4.0, ("NAME", "")) is False
    assert throttle.allow("999000002", 4.0) is True
    assert throttle.allow("999000001", 5.0, ("NAME", "Cargo")) is True
    # The interval restarts from the last update that went out.
    assert throttle.allow("999000001", 12.0, ("NAME", "Cargo")) is False
    assert throttle.allow("999000001", 15.0, ("NAME", "Cargo")) is True
    assert len(throttle) == 2


def test_throttle_with_no_interval_never_blocks() -> None:
    throttle = Throttle(0.0)
    assert throttle.allow("ffff01", 1.0) is True
    assert throttle.allow("ffff01", 1.0) is True


def test_throttle_prune_forgets_quiet_tracks() -> None:
    throttle = Throttle(2.0)
    throttle.allow("ffff01", 0.0)
    throttle.allow("ffff02", 50.0)

    assert throttle.prune(now=70.0, older_than_seconds=60.0) == ["ffff01"]
    assert len(throttle) == 1
    assert throttle.allow("ffff01", 70.0) is True
