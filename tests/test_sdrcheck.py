# SPDX-License-Identifier: Apache-2.0
"""The receiver signal gate. Every aircraft and the antenna location are synthetic."""

from collections.abc import Callable

import pytest

from tampa_cop import sdrcheck
from tampa_cop.geo import BoundingBox
from tampa_cop.sources.readsb import Aircraft, ReadsbError, Snapshot

AOI = BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)
RECEIVER = (27.90, -82.50)
THRESHOLDS = sdrcheck.Thresholds(min_aircraft=2, max_median_seen_pos=5.0, min_range_nm=30.0)


def snap(*aircraft: Aircraft, now: float, messages: int | None = None) -> Snapshot:
    """Build a snapshot; messages grow with time unless given."""
    return Snapshot(
        now=now, messages=int(now * 10) if messages is None else messages, aircraft=aircraft
    )


def new_check() -> sdrcheck.SignalCheck:
    return sdrcheck.SignalCheck(aoi=AOI, receiver=RECEIVER)


class FakeClock:
    """A clock that only moves when the code under test sleeps or a fetch takes time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# --- measurements ---


def test_counts_unique_fresh_icao_aircraft_inside_the_area() -> None:
    check = new_check()
    check.observe(
        snap(
            Aircraft("ffff01", 27.75, -82.55, 0.5),
            Aircraft("ffff02", 27.60, -82.70, 1.0),
            Aircraft("ffff03", 29.50, -82.50, 1.0),  # outside the area
            Aircraft("ffff04", 27.75, -82.55, 40.0),  # position too old
            Aircraft("~ffff05", 27.75, -82.55, 0.5),  # not an ICAO address
            Aircraft("ffff06"),  # no position
            Aircraft("ffff07", 27.75, -82.55, None),  # no position age
            now=1.0,
        )
    )
    check.observe(snap(Aircraft("ffff01", 27.76, -82.56, 0.2), now=2.0))

    assert check.aircraft_in_aoi == {"ffff01", "ffff02"}
    assert check.seen_pos_samples == [0.5, 1.0, 1.0, 40.0, 0.2]
    assert check.polls == 2
    assert check.failed_polls == check.dropouts == check.restarts == 0


def test_farthest_range_uses_fresh_plausible_positions_only() -> None:
    check = new_check()
    check.observe(
        snap(
            Aircraft("ffff01", 28.90, -82.50, 1.0),  # about 60 nm north
            Aircraft("ffff02", 29.90, -82.50, 60.0),  # farther, but stale
            Aircraft("ffff03", 45.00, -82.50, 1.0),  # about 1000 nm: a decoding error
            now=1.0,
        )
    )
    assert check.farthest_nm == pytest.approx(60.0, abs=0.1)


def test_a_falling_message_counter_is_a_restart() -> None:
    check = new_check()
    check.observe(snap(now=1.0, messages=900))
    check.observe(snap(now=2.0, messages=950))
    check.observe(snap(now=3.0, messages=12))
    check.observe(snap(now=4.0, messages=40))
    assert check.restarts == 1
    assert check.dropouts == 0


def test_each_outage_of_failed_fetches_is_one_dropout() -> None:
    check = new_check()
    check.observe(snap(now=1.0))
    for _ in range(3):
        check.observe(None)
    check.observe(snap(now=5.0))
    check.observe(None)
    check.observe(snap(now=7.0))

    assert check.failed_polls == 4
    assert check.dropouts == 2


def test_a_file_that_stops_updating_is_a_dropout_after_five_polls() -> None:
    check = new_check()
    check.observe(snap(Aircraft("ffff01", 27.75, -82.55, 0.5), now=1.0))
    for _ in range(4):
        check.observe(snap(Aircraft("ffff01", 27.75, -82.55, 0.5), now=1.0))
    assert check.dropouts == 0

    check.observe(snap(now=1.0))
    check.observe(snap(now=1.0))
    check.observe(None)  # still the same outage
    assert check.dropouts == 1
    # Repeated documents are not measured twice.
    assert check.seen_pos_samples == [0.5]

    check.observe(snap(now=9.0))
    for _ in range(5):
        check.observe(snap(now=9.0))
    assert check.dropouts == 2


def test_one_repeated_document_is_ordinary_jitter() -> None:
    check = new_check()
    for now in (1.0, 1.0, 2.0, 2.0, 3.0):
        check.observe(snap(now=now))
    assert check.dropouts == 0


# --- report ---


def passing_check() -> sdrcheck.SignalCheck:
    check = new_check()
    check.observe(
        snap(
            Aircraft("ffff01", 27.75, -82.55, 0.5),
            Aircraft("ffff02", 27.60, -82.70, 1.5),
            Aircraft("ffff03", 28.90, -82.50, 2.5),
            now=1.0,
        )
    )
    return check


def test_report_passes_when_every_mark_is_met() -> None:
    report = passing_check().report(THRESHOLDS, minutes=30.0, complete=True)

    assert report.passed is True
    assert [result.passed for result in report.results] == [True, True, True, True]
    assert [result.measured for result in report.results] == [
        "2",
        "1.5 s",
        "60 nm",
        "0 dropouts, 0 restarts",
    ]
    text = sdrcheck.format_report(report)
    assert "Watched for 30.0 minutes: 1 polls, 0 failed." in text
    assert text.count("[PASS]") == 4
    assert text.endswith("Result: PASS")
    # Counts and distances only: no addresses, no antenna location.
    assert "ffff" not in text
    assert "27.9" not in text


@pytest.mark.parametrize(
    ("thresholds", "failing"),
    [
        (sdrcheck.Thresholds(3, 5.0, 30.0), 0),
        (sdrcheck.Thresholds(2, 1.0, 30.0), 1),
        (sdrcheck.Thresholds(2, 5.0, 90.0), 2),
    ],
)
def test_report_fails_on_a_missed_mark(thresholds: sdrcheck.Thresholds, failing: int) -> None:
    report = passing_check().report(thresholds, minutes=30.0, complete=True)
    assert report.passed is False
    assert [index for index, result in enumerate(report.results) if not result.passed] == [failing]
    assert sdrcheck.format_report(report).endswith("Result: FAIL")


def test_report_fails_on_dropouts_and_restarts() -> None:
    check = passing_check()
    check.observe(None)
    check.observe(snap(now=3.0, messages=1))
    report = check.report(THRESHOLDS, minutes=30.0, complete=True)
    assert report.results[3].passed is False
    assert report.results[3].measured == "1 dropouts, 1 restarts"
    assert report.failed_polls == 1


def test_report_with_no_positions_fails_plainly() -> None:
    report = new_check().report(THRESHOLDS, minutes=1.0, complete=True)
    assert report.passed is False
    assert report.results[1].measured == "no positions"
    assert report.results[1].passed is False


def test_a_run_stopped_early_never_passes() -> None:
    report = passing_check().report(THRESHOLDS, minutes=2.0, complete=False)
    assert all(result.passed for result in report.results)
    assert report.passed is False
    assert "stopped early" in sdrcheck.format_report(report)


# --- the polling loop ---


def fetcher(
    clock: FakeClock, *, fail_when: Callable[[int], bool] = lambda _: False
) -> Callable[[], Snapshot]:
    """Return a fetch function whose documents follow the fake clock."""
    calls = 0

    def fetch() -> Snapshot:
        nonlocal calls
        calls += 1
        if fail_when(calls):
            msg = "could not reach readsb (ConnectError)"
            raise ReadsbError(msg)
        return snap(Aircraft("ffff01", 27.75, -82.55, 0.5), now=clock.now)

    return fetch


def test_polls_once_a_second_for_the_whole_run_and_reports_progress() -> None:
    clock = FakeClock()
    check = new_check()
    progress: list[tuple[int, float]] = []

    elapsed = sdrcheck.run_check(
        fetcher(clock),
        check,
        duration_seconds=150,
        clock=clock,
        sleep=clock.sleep,
        on_progress=lambda current, seconds: progress.append((current.polls, seconds)),
    )

    assert elapsed == 150
    assert check.polls == 150
    assert clock.sleeps == [1.0] * 150
    assert progress == [(61, 60.0), (121, 120.0)]
    assert check.dropouts == 0


def test_a_slow_fetch_does_not_add_extra_waiting() -> None:
    clock = FakeClock()
    check = new_check()

    def slow_fetch() -> Snapshot:
        clock.now += 2.5
        return snap(now=clock.now)

    sdrcheck.run_check(slow_fetch, check, duration_seconds=10, clock=clock, sleep=clock.sleep)

    assert clock.sleeps == []
    assert check.polls == 4


def test_gives_up_when_readsb_never_answers() -> None:
    clock = FakeClock()
    check = new_check()
    with pytest.raises(ReadsbError, match="could not reach readsb"):
        sdrcheck.run_check(
            fetcher(clock, fail_when=lambda _: True),
            check,
            duration_seconds=600,
            clock=clock,
            sleep=clock.sleep,
        )
    assert check.polls == sdrcheck.STARTUP_FAILURES_TO_ABORT - 1


def test_keeps_going_through_failures_once_readsb_has_answered() -> None:
    clock = FakeClock()
    check = new_check()

    sdrcheck.run_check(
        fetcher(clock, fail_when=lambda call: 5 <= call <= 30),
        check,
        duration_seconds=60,
        clock=clock,
        sleep=clock.sleep,
    )

    assert check.polls == 60
    assert check.failed_polls == 26
    assert check.dropouts == 1
