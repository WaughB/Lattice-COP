# SPDX-License-Identifier: Apache-2.0
"""The ingest pipelines end to end, with AISStream, readsb and Lattice all faked."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from tampa_cop import ingest
from tampa_cop.config import Settings, load_settings
from tampa_cop.sources import aisstream
from tests.builders import aircraft_entry, ais_position, ais_ship_static, time_utc

RECEIVER_URL = "http://readsb/data/aircraft.json"
# 200000001 has no assigned country code, so it is not a real vessel, but it
# passes the vessel-MMSI rule that drops the 999 range.
VESSEL_MMSI = 200000001


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, token_env: None) -> Settings:
    monkeypatch.setenv("AISSTREAM_API_KEY", "fake-aisstream-key")
    return load_settings(env_file=None)


class FakeEntities:
    """Records publishes and sets ``done`` once ``expected`` have arrived."""

    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.calls: list[dict[str, Any]] = []
        self.done = asyncio.Event()

    async def publish_entity(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if len(self.calls) >= self.expected:
            self.done.set()


class IdleConnection:
    """Sends its frames, then stays open until the task is cancelled."""

    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self._receive()

    async def _receive(self) -> AsyncIterator[str | bytes]:
        for frame in self.frames:
            yield frame
        await asyncio.Event().wait()


def connector_for(connection: IdleConnection) -> aisstream.Connector:
    @asynccontextmanager
    async def opened(_url: str) -> AsyncIterator[aisstream.Connection]:
        yield connection

    def connect(url: str) -> AbstractAsyncContextManager[aisstream.Connection]:
        return opened(url)

    return connect


async def stop_when(done: asyncio.Event, stop: asyncio.Event) -> None:
    await asyncio.wait_for(done.wait(), timeout=5)
    stop.set()


# --- supervise ---


async def test_supervise_cancels_everything_when_stopped() -> None:
    stop = asyncio.Event()
    started = asyncio.Event()
    cancelled: list[str] = []

    async def work(name: str) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    runner = asyncio.create_task(ingest.supervise(stop, work("a"), work("b")))
    await started.wait()
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(runner, timeout=5)
    assert sorted(cancelled) == ["a", "b"]


async def test_supervise_raises_when_a_worker_dies() -> None:
    async def broken() -> None:
        msg = "pipeline bug"
        raise RuntimeError(msg)

    async def idle() -> None:
        await asyncio.Event().wait()

    with pytest.raises(RuntimeError, match="pipeline bug"):
        await asyncio.wait_for(ingest.supervise(asyncio.Event(), broken(), idle()), timeout=5)


# --- AIS ---


async def test_ais_pipeline_cleans_merges_static_data_and_publishes(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tampa_cop.ingest")
    now = datetime.now(UTC)
    frames = [
        json.dumps(message).encode()
        for message in (
            ais_ship_static(VESSEL_MMSI, at=now),
            ais_position(VESSEL_MMSI, at=now),
            ais_position(999000002, at=now),  # dropped: not a vessel MMSI
            ais_position(VESSEL_MMSI, point=(29.0, -82.5), at=now),  # dropped: outside the AOI
        )
    ]
    connection = IdleConnection(frames)
    entities, stop = FakeEntities(expected=1), asyncio.Event()

    await asyncio.gather(
        ingest.run_ais(settings, entities, stop, connector=connector_for(connection)),
        stop_when(entities.done, stop),
    )

    assert json.loads(connection.sent[0])["APIKey"] == "fake-aisstream-key"
    (call,) = entities.calls
    assert call["entity_id"] == f"tampa-cop-ais-{VESSEL_MMSI}"
    assert call["aliases"].name == "SYNTHETIC ONE"
    assert call["description"].startswith("Cargo; 190 m x 32 m")
    assert call["location"].position.latitude_degrees == 27.75

    stopped = caplog.records[-1]
    assert stopped.getMessage() == "ais-ingest stopped; tracks will expire in Lattice"
    assert stopped.clean == {"static_cached": 1, "kept": 1, "mmsi_not_vessel": 1, "outside_aoi": 1}
    assert stopped.publish == {"submitted": 1, "published": 1}
    assert stopped.vessels_tracked == 1
    assert stopped.backlog == 0
    assert "fake-aisstream-key" not in caplog.text


async def test_ais_pipeline_logs_its_counts_every_minute(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tampa_cop.ingest")
    stop = asyncio.Event()
    waits: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) >= 2:
            stop.set()
        await asyncio.sleep(0)

    connection = IdleConnection(
        [json.dumps(ais_position(VESSEL_MMSI, at=datetime.now(UTC))).encode()]
    )
    await asyncio.wait_for(
        ingest.run_ais(
            settings, FakeEntities(1), stop, connector=connector_for(connection), sleep=fast_sleep
        ),
        timeout=5,
    )

    assert waits[0] == 60.0
    counts = [r for r in caplog.records if r.getMessage() == "ais-ingest counts"]
    assert counts
    assert counts[0].stream["messages"]["PositionReport"] == 1
    assert counts[0].clean == {"kept": 1}


# --- ADS-B ---


def readsb_answers(*documents: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """Answer successive polls with the given documents, repeating the last one."""
    remaining = list(documents)

    def respond(_request: httpx.Request) -> httpx.Response:
        document = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if "error" in document:
            return httpx.Response(int(document["error"]))
        return httpx.Response(200, json=document)

    return respond


@respx.mock
async def test_adsb_pipeline_polls_cleans_and_publishes(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tampa_cop.ingest")
    now = datetime.now(UTC).timestamp()
    first = {
        "now": now,
        "messages": 100,
        "aircraft": [
            aircraft_entry("ffff01", flight="SYN101  ", alt_geom=35000, gs=450.0, track=90.0),
            aircraft_entry("ffff02", None, None),
            aircraft_entry("~ffff03"),
        ],
    }
    second = {
        "now": now + 1,
        "messages": 200,
        "aircraft": [aircraft_entry("ffff04", (27.60, -82.70), alt_baro=3000)],
    }
    route = respx.get(RECEIVER_URL).mock(
        side_effect=readsb_answers(first, {"error": 503}, first, second)
    )
    entities, stop = FakeEntities(expected=2), asyncio.Event()

    async def no_wait(_seconds: float) -> None:
        await asyncio.sleep(0)

    await asyncio.gather(
        ingest.run_adsb(settings, entities, stop, sleep=no_wait),
        stop_when(entities.done, stop),
    )

    assert route.call_count >= 4
    by_id = {call["entity_id"]: call for call in entities.calls}
    assert set(by_id) == {"tampa-cop-adsb-ffff01", "tampa-cop-adsb-ffff04"}
    aircraft = by_id["tampa-cop-adsb-ffff01"]
    assert aircraft["aliases"].name == "SYN101"
    assert aircraft["location"].position.altitude_hae_meters == pytest.approx(10668.0)
    assert aircraft["mil_view"].environment == "ENVIRONMENT_AIR"
    assert by_id["tampa-cop-adsb-ffff04"]["description"] == (
        "barometric altitude 3,000 ft; altitude approximate"
    )
    assert by_id["tampa-cop-adsb-ffff04"]["transponder_codes"].mode_c_altitude_ft == 3000
    assert aircraft["transponder_codes"].mode_s.address == 0xFFFF01

    stopped = caplog.records[-1]
    assert stopped.getMessage() == "adsb-ingest stopped; tracks will expire in Lattice"
    assert stopped.clean["kept"] == 2
    assert stopped.clean["no_position"] == 1
    assert stopped.clean["non_icao"] == 1
    assert stopped.polls["failed_polls"] == 1
    # The repeated first document was not cleaned or published twice.
    assert stopped.polls["unchanged_polls"] >= 1
    assert stopped.publish["published"] == 2


@respx.mock
async def test_adsb_pipeline_keeps_polling_when_readsb_is_down_and_logs_counts(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tampa_cop.ingest")
    respx.get(RECEIVER_URL).mock(side_effect=httpx.ConnectError("refused"))
    stop = asyncio.Event()
    waits: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) >= 6:
            stop.set()
        await asyncio.sleep(0)

    async with httpx.AsyncClient() as client:
        await asyncio.wait_for(
            ingest.run_adsb(settings, FakeEntities(1), stop, client=client, sleep=fast_sleep),
            timeout=5,
        )
        assert not client.is_closed

    counts = [r for r in caplog.records if r.getMessage() == "adsb-ingest counts"]
    assert counts
    stopped = caplog.records[-1]
    assert stopped.polls["failed_polls"] == stopped.polls["polls"] >= 2
    assert stopped.publish == {}
    assert stopped.aircraft_tracked == 0


def test_time_helper_is_readable_by_the_cleaner() -> None:
    assert time_utc(datetime(2026, 1, 1, tzinfo=UTC)).endswith("+0000 UTC")
