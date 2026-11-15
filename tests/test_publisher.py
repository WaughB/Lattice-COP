# SPDX-License-Identifier: Apache-2.0
"""The Lattice publisher: throttle, newest-wins queue, retries. Lattice is faked."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from anduril.core.api_error import ApiError

from lattice_cop.clean.throttle import Throttle
from lattice_cop.lattice import publisher as pub
from lattice_cop.models import Source, Track
from tests.builders import T0

SECRET_HEADER = "Bearer fake-secret-token"  # noqa: S105 - test value, not a credential


def track(key: str = "999000001", latitude: float = 27.75, name: str = "SYNTHETIC ONE") -> Track:
    return Track(Source.AIS, key, name, latitude, -82.55, T0)


def api_error(status: int) -> ApiError:
    return ApiError(
        status_code=status,
        headers={"authorization": SECRET_HEADER},
        body={"message": f"status {status}"},
    )


class FakeEntities:
    """Records every publish; answers from a script of errors (``None`` means success)."""

    def __init__(self, script: list[Exception | None] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []
        self.gate: asyncio.Event | None = None

    async def publish_entity(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.gate is not None:
            await self.gate.wait()
        outcome = self.script.pop(0) if self.script else None
        if outcome is not None:
            raise outcome


class Clock:
    """Monotonic and wall clocks that move only when told to."""

    def __init__(self) -> None:
        self.seconds = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.seconds

    def wall(self) -> datetime:
        return T0 + timedelta(seconds=self.seconds - 1000.0)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.seconds += seconds


def make(entities: FakeEntities, clock: Clock, **kwargs: Any) -> pub.Publisher:
    return pub.Publisher(
        entities,
        expiry_seconds=kwargs.pop("expiry_seconds", 600.0),
        throttle=Throttle(kwargs.pop("interval", 10.0)),
        sleep=clock.sleep,
        rng=lambda: 1.0,
        monotonic=clock.monotonic,
        wall_clock=clock.wall,
        **kwargs,
    )


@pytest.fixture
async def running() -> AsyncIterator[tuple[pub.Publisher, FakeEntities, Clock]]:
    """A publisher with its workers running, stopped again after the test."""
    entities, clock = FakeEntities(), Clock()
    publisher = make(entities, clock)
    task = asyncio.create_task(publisher.run())
    yield publisher, entities, clock
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


Running = tuple[pub.Publisher, FakeEntities, Clock]


# --- pure helpers ---


@pytest.mark.parametrize(
    ("status", "retry"),
    [(408, True), (429, True), (500, True), (503, True), (599, True), (400, False), (401, False),
     (403, False), (404, False), (422, False), (200, False), (None, False)],
)  # fmt: skip
def test_only_408_429_and_5xx_are_retried(status: int | None, retry: bool) -> None:
    assert pub.is_retryable(status) is retry


def test_retry_delay_doubles_and_is_capped() -> None:
    assert [pub.retry_delay(n, rng=lambda: 1.0) for n in range(1, 7)] == [0.5, 1, 2, 4, 8, 8]
    assert pub.retry_delay(3, rng=lambda: 0.0) == 1.0
    assert 0.25 <= pub.retry_delay(1) <= 0.5
    assert pub.retry_delay(0, rng=lambda: 1.0) == 0.5


# --- publishing ---


async def test_publishes_with_expiry_counted_from_the_publish_time(running: Running) -> None:
    publisher, entities, clock = running
    clock.seconds += 45  # the message is 45 s old by the time it goes out

    assert publisher.submit(track()) is True
    await publisher.drain()

    (call,) = entities.calls
    assert call["entity_id"] == "lattice-cop-ais-999000001"
    assert call["created_time"] == clock.wall()
    assert call["expiry_time"] == clock.wall() + timedelta(seconds=600)
    assert call["provenance"].source_update_time == T0
    assert publisher.counts == {"submitted": 1, "published": 1}
    assert publisher.backlog == 0


async def test_created_time_is_the_first_sighting(running: Running) -> None:
    publisher, entities, clock = running
    first_seen = clock.wall()
    publisher.submit(track())
    await publisher.drain()
    clock.seconds += 30
    publisher.submit(track(latitude=27.76))
    await publisher.drain()

    assert [call["created_time"] for call in entities.calls] == [first_seen, first_seen]
    assert entities.calls[1]["expiry_time"] == first_seen + timedelta(seconds=630)


async def test_throttle_holds_back_unchanged_updates_but_not_changed_ones(running: Running) -> None:
    publisher, entities, clock = running
    assert publisher.submit(track(), ("SYNTHETIC ONE", "")) is True
    clock.seconds += 3
    assert publisher.submit(track(latitude=27.76), ("SYNTHETIC ONE", "")) is False
    assert publisher.submit(track(latitude=27.76), ("SYNTHETIC ONE", "Cargo")) is True
    assert publisher.submit(track("999000002")) is True
    await publisher.drain()

    assert publisher.counts == {"submitted": 4, "throttled": 1, "superseded": 1, "published": 2}
    # The newer report replaced the one still waiting, so the vessel was sent once.
    assert sorted(call["entity_id"] for call in entities.calls) == [
        "lattice-cop-ais-999000001",
        "lattice-cop-ais-999000002",
    ]
    assert entities.calls[0]["location"].position.latitude_degrees == 27.76


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_transient_errors_are_retried_with_backoff(status: int, running: Running) -> None:
    publisher, entities, clock = running
    entities.script = [api_error(status), api_error(status), None]

    publisher.submit(track())
    await publisher.drain()

    assert len(entities.calls) == 3
    assert clock.sleeps == [0.5, 1.0]
    assert publisher.counts == {"submitted": 1, "retried": 2, "published": 1}
    # Each try carries a fresh expiry.
    assert entities.calls[2]["expiry_time"] > entities.calls[0]["expiry_time"]


async def test_network_failures_are_retried(running: Running) -> None:
    publisher, entities, _ = running
    entities.script = [httpx.ConnectError("reset"), httpx.ReadTimeout("slow"), None]
    publisher.submit(track())
    await publisher.drain()
    assert publisher.counts == {"submitted": 1, "retried": 2, "published": 1}


async def test_gives_up_after_the_last_attempt_and_logs_once(
    running: Running, caplog: pytest.LogCaptureFixture
) -> None:
    publisher, entities, clock = running
    caplog.set_level(logging.ERROR, logger="lattice_cop.lattice.publisher")
    entities.script = [api_error(503)] * 4 + [httpx.ConnectError("reset")] * 4

    publisher.submit(track())
    publisher.submit(track("999000002"))
    await publisher.drain()

    assert len(entities.calls) == 8
    assert publisher.counts == {"submitted": 2, "retried": 6, "failed": 2}
    assert sorted(clock.sleeps) == [0.5, 0.5, 1.0, 1.0, 2.0, 2.0]
    messages = [(r.getMessage(), r.status_code, r.detail) for r in caplog.records]
    assert sorted(messages, key=str) == sorted(
        [
            ("gave up publishing an entity after retries", 503, "{'message': 'status 503'}"),
            ("gave up publishing an entity after retries", None, "ConnectError"),
        ],
        key=str,
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_validation_errors_are_never_retried_and_are_logged_with_the_entity_id(
    status: int, running: Running, caplog: pytest.LogCaptureFixture
) -> None:
    publisher, entities, clock = running
    caplog.set_level(logging.ERROR, logger="lattice_cop.lattice.publisher")
    entities.script = [api_error(status)]

    publisher.submit(track())
    await publisher.drain()

    assert len(entities.calls) == 1
    assert clock.sleeps == []
    assert publisher.counts == {"submitted": 1, "rejected": 1}
    (record,) = caplog.records
    assert record.getMessage() == "Lattice rejected an entity"
    assert record.entity_id == "lattice-cop-ais-999000001"
    assert record.status_code == status
    assert record.detail == f"{{'message': 'status {status}'}}"
    # The error's headers hold a token; they must never reach the log.
    assert SECRET_HEADER not in caplog.text
    assert "authorization" not in caplog.text.lower()


async def test_repeated_errors_of_one_kind_are_logged_once_per_interval(
    running: Running, caplog: pytest.LogCaptureFixture
) -> None:
    publisher, entities, clock = running
    caplog.set_level(logging.ERROR, logger="lattice_cop.lattice.publisher")
    entities.script = [api_error(401)] * 3 + [api_error(400), api_error(401)]

    for key in ("999000001", "999000002", "999000003"):
        publisher.submit(track(key))
    await publisher.drain()
    publisher.submit(track("999000004"))
    await publisher.drain()
    clock.seconds += 31
    publisher.submit(track("999000005"))
    await publisher.drain()

    assert publisher.counts["rejected"] == 5
    assert [record.status_code for record in caplog.records] == [401, 400, 401]


async def test_a_newer_report_replaces_one_that_is_being_retried() -> None:
    entities, clock = FakeEntities([api_error(503), None]), Clock()
    publisher = make(entities, clock, interval=0.0, concurrency=1)
    entities.gate = asyncio.Event()
    task = asyncio.create_task(publisher.run())

    publisher.submit(track(latitude=27.75))
    await asyncio.sleep(0)  # the worker picks it up and waits inside the fake
    await asyncio.sleep(0)
    publisher.submit(track(latitude=27.80))  # arrives while the first is in flight
    entities.gate.set()
    await publisher.drain()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [call["location"].position.latitude_degrees for call in entities.calls] == [27.75, 27.80]
    assert clock.sleeps == []
    assert publisher.counts == {"submitted": 2, "superseded": 1, "published": 1}


async def test_prune_forgets_tracks_that_went_quiet(running: Running) -> None:
    publisher, entities, clock = running
    publisher.submit(track("999000001"))
    await publisher.drain()
    clock.seconds += 3000
    publisher.submit(track("999000002"))
    await publisher.drain()

    assert publisher.prune() == 0
    clock.seconds += 700
    assert publisher.prune() == 1

    # The forgotten vessel starts again: new first-seen time, no throttle memory.
    publisher.submit(track("999000001"))
    await publisher.drain()
    assert entities.calls[2]["created_time"] == clock.wall()
    assert entities.calls[2]["created_time"] > entities.calls[0]["created_time"]


async def test_default_clocks_work() -> None:
    entities = FakeEntities()
    publisher = pub.Publisher(entities, expiry_seconds=60.0, throttle=Throttle(2.0))
    task = asyncio.create_task(publisher.run())
    before = datetime.now(UTC)
    publisher.submit(track())
    await publisher.drain()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert before <= entities.calls[0]["created_time"] <= datetime.now(UTC)
