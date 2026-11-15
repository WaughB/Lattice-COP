# SPDX-License-Identifier: Apache-2.0
"""The receiver signal gate behind ``sdr-check``.

It polls readsb's aircraft.json once a second and decides whether the RTL-SDR
and antenna are good enough to be the ADS-B source. The report carries counts
and distances only: no aircraft addresses, and never the antenna location.
"""

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from lattice_cop.geo import BoundingBox, distance_nm
from lattice_cop.sources.readsb import ReadsbError, Snapshot

POLL_INTERVAL_SECONDS: Final = 1.0
PROGRESS_INTERVAL_SECONDS: Final = 60.0

FRESH_POSITION_SECONDS: Final = 15.0
"""A position older than this is not counted as currently received."""

MAX_PLAUSIBLE_RANGE_NM: Final = 300.0
"""Beyond line of sight for 1090 MHz; a farther position is a decoding error."""

STALE_POLLS_FOR_DROPOUT: Final = 5
"""This many polls in a row without a newer aircraft.json count as a dropout."""

STARTUP_FAILURES_TO_ABORT: Final = 10
"""Give up if this many polls fail before readsb has answered even once."""


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Pass marks for the gate. They come from settings."""

    min_aircraft: int
    max_median_seen_pos: float
    min_range_nm: float


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One line of the report."""

    name: str
    passed: bool
    measured: str
    required: str


@dataclass(frozen=True, slots=True)
class Report:
    """The outcome of a run."""

    results: tuple[CheckResult, ...]
    minutes: float
    polls: int
    failed_polls: int
    complete: bool

    @property
    def passed(self) -> bool:
        """Whether the run finished and every check passed."""
        return self.complete and all(result.passed for result in self.results)


@dataclass
class SignalCheck:
    """Collects what the gate measures, one aircraft.json at a time.

    Args:
        aoi: Area of interest.
        receiver: Antenna ``(latitude, longitude)``. Used for range only; never reported.
    """

    aoi: BoundingBox
    receiver: tuple[float, float]
    polls: int = 0
    failed_polls: int = 0
    dropouts: int = 0
    restarts: int = 0
    farthest_nm: float = 0.0
    aircraft_in_aoi: set[str] = field(default_factory=set)
    seen_pos_samples: list[float] = field(default_factory=list)
    _last_now: float | None = None
    _last_messages: int | None = None
    _stale_streak: int = 0
    _in_outage: bool = False

    @property
    def has_answered(self) -> bool:
        """Whether readsb has returned at least one good document."""
        return self._last_now is not None

    def observe(self, snapshot: Snapshot | None) -> None:
        """Record one poll. ``None`` means the fetch failed."""
        self.polls += 1
        if snapshot is None:
            self.failed_polls += 1
            self._start_outage()
            return

        if self._last_messages is not None and snapshot.messages < self._last_messages:
            self.restarts += 1
        self._last_messages = snapshot.messages

        if self._last_now is not None and snapshot.now <= self._last_now:
            # readsb has not rewritten the file. One repeat is normal timing jitter.
            self._stale_streak += 1
            if self._stale_streak >= STALE_POLLS_FOR_DROPOUT:
                self._start_outage()
            return
        self._last_now = snapshot.now
        self._stale_streak = 0
        self._in_outage = False
        self._measure(snapshot)

    def _start_outage(self) -> None:
        """Count a dropout once, however many polls the outage lasts."""
        if not self._in_outage:
            self._in_outage = True
            self.dropouts += 1

    def _measure(self, snapshot: Snapshot) -> None:
        """Add one fresh document's aircraft to the measurements."""
        for aircraft in snapshot.aircraft:
            position = aircraft.position
            if position is None or aircraft.seen_pos is None or not aircraft.is_icao:
                continue
            self.seen_pos_samples.append(aircraft.seen_pos)
            if aircraft.seen_pos > FRESH_POSITION_SECONDS:
                continue
            if self.aoi.contains(*position):
                self.aircraft_in_aoi.add(aircraft.hex)
            distance = distance_nm(*self.receiver, *position)
            if distance <= MAX_PLAUSIBLE_RANGE_NM:
                self.farthest_nm = max(self.farthest_nm, distance)

    def report(self, thresholds: Thresholds, *, minutes: float, complete: bool) -> Report:
        """Compare the measurements with the pass marks."""
        count = len(self.aircraft_in_aoi)
        median = statistics.median(self.seen_pos_samples) if self.seen_pos_samples else None
        results = (
            CheckResult(
                "Unique aircraft with a position inside the AOI",
                count >= thresholds.min_aircraft,
                str(count),
                f"at least {thresholds.min_aircraft}",
            ),
            CheckResult(
                "Median position age (seen_pos)",
                median is not None and median <= thresholds.max_median_seen_pos,
                "no positions" if median is None else f"{median:.1f} s",
                f"{thresholds.max_median_seen_pos:g} s or less",
            ),
            CheckResult(
                "Farthest position from the antenna",
                self.farthest_nm >= thresholds.min_range_nm,
                f"{self.farthest_nm:.0f} nm",
                f"at least {thresholds.min_range_nm:g} nm",
            ),
            CheckResult(
                "USB dropouts and readsb restarts",
                self.dropouts == 0 and self.restarts == 0,
                f"{self.dropouts} dropouts, {self.restarts} restarts",
                "none",
            ),
        )
        return Report(
            results=results,
            minutes=minutes,
            polls=self.polls,
            failed_polls=self.failed_polls,
            complete=complete,
        )


def format_report(report: Report) -> str:
    """Render the report as plain text for the terminal."""
    width = max(len(result.name) for result in report.results)
    lines = [
        "Receiver signal gate",
        f"  Watched for {report.minutes:.1f} minutes: {report.polls} polls, "
        f"{report.failed_polls} failed.",
        "",
    ]
    lines += [
        f"  [{'PASS' if result.passed else 'FAIL'}] {result.name.ljust(width)}  "
        f"{result.measured}  (need {result.required})"
        for result in report.results
    ]
    lines.append("")
    if not report.complete:
        lines.append("Result: FAIL (the run was stopped early, so it does not count)")
    elif report.passed:
        lines.append("Result: PASS")
    else:
        lines.append("Result: FAIL")
    return "\n".join(lines)


def run_check(  # noqa: PLR0913 - the extra arguments are test seams
    fetch: Callable[[], Snapshot],
    check: SignalCheck,
    *,
    duration_seconds: float,
    interval_seconds: float = POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_progress: Callable[[SignalCheck, float], None] | None = None,
) -> float:
    """Poll readsb until ``duration_seconds`` have passed.

    Args:
        fetch: Returns the current aircraft.json, or raises ``ReadsbError``.
        check: Receives every poll.
        duration_seconds: How long to watch.
        interval_seconds: Time between polls.
        clock: Monotonic clock. Tests pass a fake.
        sleep: Waits between polls. Tests pass a fake.
        on_progress: Called about once a minute with the check and the elapsed seconds.

    Returns:
        The elapsed time in seconds.

    Raises:
        ReadsbError: If readsb never answers during the first polls.
    """
    start = clock()
    next_progress = PROGRESS_INTERVAL_SECONDS
    while (elapsed := clock() - start) < duration_seconds:
        try:
            snapshot: Snapshot | None = fetch()
        except ReadsbError:
            if not check.has_answered and check.polls + 1 >= STARTUP_FAILURES_TO_ABORT:
                raise
            snapshot = None
        check.observe(snapshot)
        if on_progress is not None and elapsed >= next_progress:
            on_progress(check, elapsed)
            next_progress += PROGRESS_INTERVAL_SECONDS
        delay = start + check.polls * interval_seconds - clock()
        if delay > 0:
            sleep(delay)
    return clock() - start
