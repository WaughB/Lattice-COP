# SPDX-License-Identifier: Apache-2.0
"""AISStream client: subscription, counting, reconnects. No test reaches AISStream.

Most tests use a fake connection. One starts a mock AISStream server on
127.0.0.1 to exercise the real WebSocket library. Every vessel is synthetic.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import pytest
from pydantic import SecretStr
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError

from lattice_cop.geo import BoundingBox
from lattice_cop.sources import aisstream as stream

FAKE_KEY = SecretStr("fake-aisstream-key")
AOI = BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)
IN_AOI = (27.75, -82.55)
OUTSIDE_AOI = (30.00, -82.55)


class StopLoopError(Exception):
    """Raised by a fake to end an otherwise endless loop."""


def position(
    kind: str = "PositionReport",
    point: tuple[float, float] = IN_AOI,
    mmsi: int = 999000001,
) -> dict[str, Any]:
    """Build a synthetic position message in AISStream's envelope."""
    return {
        "MessageType": kind,
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": "SYNTHETIC ONE",
            "Latitude": point[0],
            "Longitude": point[1],
        },
        "Message": {
            kind: {
                "UserID": mmsi,
                "Latitude": point[0],
                "Longitude": point[1],
                "Sog": 8.2,
                "Cog": 91.0,
                "TrueHeading": 90,
                "Valid": True,
            }
        },
    }


def static(kind: str = "ShipStaticData", mmsi: int = 999000001) -> dict[str, Any]:
    """Build a synthetic static-data message."""
    return {
        "MessageType": kind,
        "MetaData": {"MMSI": mmsi, "ShipName": "SYNTHETIC ONE"},
        "Message": {kind: {"UserID": mmsi, "Name": "SYNTHETIC ONE", "Valid": True}},
    }


def confirmation(*, compressed: bool = True) -> dict[str, Any]:
    """Build the server's subscription confirmation."""
    return {
        "MessageType": "SubscriptionConfirmation",
        "Message": {"CompressionEnabled": compressed},
    }


def frame(message: object) -> bytes:
    """Encode a message the way AISStream sends it: UTF-8 JSON in a binary frame."""
    return json.dumps(message).encode()


class FakeConnection:
    """A scripted connection: yields frames, then closes cleanly or with an error."""

    def __init__(
        self,
        frames: Sequence[str | bytes] = (),
        error: Exception | None = None,
        send_delay: float = 0,
    ) -> None:
        self.frames = list(frames)
        self.error = error
        self.send_delay = send_delay
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        await asyncio.sleep(self.send_delay)
        self.sent.append(message)

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self._receive()

    async def _receive(self) -> AsyncIterator[str | bytes]:
        for item in self.frames:
            yield item
        if self.error is not None:
            raise self.error


class FakeConnector:
    """Hands out scripted connections in order; an exception means the connect fails."""

    def __init__(self, outcomes: Sequence[FakeConnection | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []

    def __call__(self, url: str) -> AbstractAsyncContextManager[stream.Connection]:
        self.urls.append(url)
        return self._open(self.outcomes.pop(0))

    @staticmethod
    @asynccontextmanager
    async def _open(outcome: FakeConnection | Exception) -> AsyncIterator[stream.Connection]:
        if isinstance(outcome, Exception):
            raise outcome
        yield outcome


class FakeSleep:
    """Records each requested delay and stops the loop after ``limit`` calls."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if len(self.delays) >= self.limit:
            raise StopLoopError


async def run_scripted(
    outcomes: Sequence[FakeConnection | Exception],
    stats: stream.StreamStats | None = None,
    received: list[dict[str, Any]] | None = None,
) -> tuple[FakeConnector, FakeSleep, stream.StreamStats]:
    """Run the stream over scripted connections until they are used up."""
    connector = FakeConnector(outcomes)
    sleep = FakeSleep(limit=len(outcomes))
    stats = stats or stream.StreamStats()
    with pytest.raises(StopLoopError):
        await stream.run_stream(
            FAKE_KEY,
            AOI,
            stats=stats,
            on_message=received.append if received is not None else None,
            connector=connector,
            sleep=sleep,
            rng=lambda: 1.0,
        )
    return connector, sleep, stats


def count(frame_or_message: object, stats: stream.StreamStats, **kwargs: Any) -> bool:
    """Feed one message to ``handle_frame`` with the test area and key."""
    raw = (
        frame_or_message if isinstance(frame_or_message, (str, bytes)) else frame(frame_or_message)
    )
    return stream.handle_frame(raw, aoi=AOI, stats=stats, api_key=FAKE_KEY, **kwargs)


# --- subscription and backoff ---


def test_subscription_has_the_key_the_area_and_the_four_message_types() -> None:
    assert stream.build_subscription(FAKE_KEY, AOI) == {
        "APIKey": "fake-aisstream-key",
        "BoundingBoxes": [[[27.40, -83.00], [28.20, -82.25]]],
        "FilterMessageTypes": [
            "PositionReport",
            "StandardClassBPositionReport",
            "ShipStaticData",
            "StaticDataReport",
        ],
    }


def test_backoff_doubles_from_two_seconds_and_stops_at_sixty() -> None:
    top = [stream.backoff_delay(attempt, rng=lambda: 1.0) for attempt in range(8)]
    assert top == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]


@pytest.mark.parametrize("attempt", [-1, 0, 1, 2, 5, 50, 5000])
@pytest.mark.parametrize("roll", [0.0, 0.5, 0.999])
def test_backoff_stays_between_two_and_sixty_seconds(attempt: int, roll: float) -> None:
    delay = stream.backoff_delay(attempt, rng=lambda: roll)
    assert stream.BACKOFF_MIN_SECONDS <= delay <= stream.BACKOFF_MAX_SECONDS


def test_backoff_jitter_spreads_the_delay() -> None:
    assert stream.backoff_delay(3, rng=lambda: 0.0) == 8.0
    assert stream.backoff_delay(3, rng=lambda: 1.0) == 16.0
    assert stream.BACKOFF_MIN_SECONDS <= stream.backoff_delay(3) <= 16.0


# --- counting frames ---


@pytest.mark.parametrize("kind", ["PositionReport", "StandardClassBPositionReport"])
def test_position_inside_the_area_is_counted(kind: str) -> None:
    stats = stream.StreamStats()
    received: list[dict[str, Any]] = []

    assert count(position(kind), stats, on_message=received.append) is True

    assert stats.by_type[kind] == 1
    assert stats.positions_in_aoi == 1
    assert stats.positions_outside_aoi == 0
    assert stats.total_messages == 1
    assert received == [position(kind)]


def test_text_frames_are_accepted_too() -> None:
    stats = stream.StreamStats()
    assert count(json.dumps(position()), stats) is True
    assert stats.positions_in_aoi == 1


def test_position_outside_the_area_is_counted_separately() -> None:
    stats = stream.StreamStats()
    assert count(position(point=OUTSIDE_AOI), stats) is True
    assert stats.positions_in_aoi == 0
    assert stats.positions_outside_aoi == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"Latitude": IN_AOI[0], "Longitude": IN_AOI[1]},
        {"latitude": IN_AOI[0], "longitude": IN_AOI[1]},
    ],
)
def test_position_falls_back_to_metadata_in_either_case(metadata: dict[str, float]) -> None:
    message = position()
    message["Message"]["PositionReport"] = {"UserID": 999000001}
    message["MetaData"] = metadata
    assert stream.extract_position(message, "PositionReport") == IN_AOI


@pytest.mark.parametrize(
    "message",
    [
        {"MessageType": "PositionReport"},
        {"MessageType": "PositionReport", "Message": "not an object", "MetaData": []},
        {"MessageType": "PositionReport", "Message": {"PositionReport": {"Latitude": 27.75}}},
        {
            "MessageType": "PositionReport",
            "Message": {"PositionReport": {"Latitude": True, "Longitude": "-82.55"}},
        },
    ],
)
def test_position_without_usable_coordinates_counts_as_outside(message: dict[str, Any]) -> None:
    stats = stream.StreamStats()
    assert stream.extract_position(message, "PositionReport") is None
    assert count(message, stats) is True
    assert stats.positions_outside_aoi == 1


@pytest.mark.parametrize("kind", ["ShipStaticData", "StaticDataReport"])
def test_static_messages_are_counted_without_a_position(kind: str) -> None:
    stats = stream.StreamStats()
    assert count(static(kind), stats) is True
    assert stats.by_type[kind] == 1
    assert stats.positions_in_aoi == stats.positions_outside_aoi == 0


@pytest.mark.parametrize("raw", [b"not json", b"\xff\xfe", "[1, 2, 3]", '"text"'])
def test_frames_that_are_not_json_objects_are_counted_as_invalid(raw: str | bytes) -> None:
    stats = stream.StreamStats()
    assert count(raw, stats) is False
    assert stats.invalid_frames == 1
    assert stats.total_messages == 0


@pytest.mark.parametrize("kind", ["AidsToNavigationReport", None, 7, ["PositionReport"]])
def test_unsubscribed_message_types_are_counted_as_other(kind: object) -> None:
    stats = stream.StreamStats()
    received: list[dict[str, Any]] = []
    assert count({"MessageType": kind}, stats, on_message=received.append) is False
    assert stats.by_type["other"] == 1
    assert received == []


def test_server_error_is_logged_without_the_api_key(caplog: pytest.LogCaptureFixture) -> None:
    stats = stream.StreamStats()
    caplog.set_level(logging.ERROR, logger="lattice_cop.sources.aisstream")

    assert count({"error": "Api Key fake-aisstream-key Is Not Valid " + "x" * 500}, stats) is False

    assert stats.server_errors == 1
    record = caplog.records[-1]
    assert record.detail.startswith("Api Key [redacted] Is Not Valid")
    assert len(record.detail) == 200
    assert "fake-aisstream-key" not in caplog.text


def test_redaction_leaves_text_alone_when_the_key_is_empty() -> None:
    assert stream._redact("closed", SecretStr("")) == "closed"


def test_confirmation_with_compression_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    stats = stream.StreamStats()
    caplog.set_level(logging.INFO, logger="lattice_cop.sources.aisstream")

    assert count(confirmation(compressed=True), stats) is False

    assert caplog.records[-1].levelname == "INFO"
    assert caplog.records[-1].compression is True
    assert stats.total_messages == 0
    assert sum(stats.by_type.values()) == 0


@pytest.mark.parametrize(
    "message",
    [confirmation(compressed=False), {"MessageType": "SubscriptionConfirmation"}],
)
def test_confirmation_without_compression_warns(
    message: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="lattice_cop.sources.aisstream")
    assert count(message, stream.StreamStats()) is False
    assert caplog.records[-1].levelname == "WARNING"
    assert caplog.records[-1].compression is False


def test_drain_reports_interval_counts_and_keeps_totals() -> None:
    stats = stream.StreamStats()
    count(position(), stats)
    count(position(point=OUTSIDE_AOI), stats)
    count(static(), stats)
    count(b"junk", stats)
    count({"error": "nope"}, stats)
    stats.connections_opened = 1

    first = stats.drain()
    second = stats.drain()

    assert first == {
        "messages": {
            "PositionReport": 2,
            "StandardClassBPositionReport": 0,
            "ShipStaticData": 1,
            "StaticDataReport": 0,
            "other": 0,
        },
        "positions_in_aoi": 1,
        "positions_outside_aoi": 1,
        "invalid_frames": 1,
        "server_errors": 1,
        "connections_opened": 1,
        "total_messages": 3,
        "total_positions_in_aoi": 1,
    }
    assert sum(second["messages"].values()) == 0
    assert second["positions_in_aoi"] == second["invalid_frames"] == second["server_errors"] == 0
    assert second["total_messages"] == 3
    assert second["total_positions_in_aoi"] == 1


# --- the connection loop ---


async def test_subscribes_first_then_counts_and_reconnects_after_a_clean_close() -> None:
    first = FakeConnection([frame(confirmation()), frame(position()), frame(static())])
    second = FakeConnection([frame(position(kind="StandardClassBPositionReport"))])
    received: list[dict[str, Any]] = []

    connector, sleep, stats = await run_scripted([first, second], received=received)

    assert connector.urls == [stream.AISSTREAM_URL, stream.AISSTREAM_URL]
    for connection in (first, second):
        assert [json.loads(sent) for sent in connection.sent] == [
            stream.build_subscription(FAKE_KEY, AOI)
        ]
    assert stats.connections_opened == 2
    assert stats.total_messages == 3
    assert [message["MessageType"] for message in received] == [
        "PositionReport",
        "ShipStaticData",
        "StandardClassBPositionReport",
    ]
    # Data arrived on both connections, so each retry uses the shortest delay.
    assert sleep.delays == [2.0, 2.0]


async def test_backoff_grows_while_no_data_arrives_and_resets_once_it_does() -> None:
    outcomes: list[FakeConnection | Exception] = [
        OSError("network unreachable"),
        TimeoutError("handshake timed out"),
        FakeConnection([frame(confirmation())]),
        FakeConnection(error=ConnectionClosedError(None, None)),
        FakeConnection([frame(position())], error=ConnectionClosedError(None, None)),
        OSError("network unreachable"),
    ]

    _, sleep, stats = await run_scripted(outcomes)

    assert sleep.delays == [2.0, 4.0, 8.0, 16.0, 2.0, 4.0]
    assert stats.connections_opened == 3
    assert stats.total_messages == 1


async def test_a_subscription_that_cannot_be_sent_in_time_is_retried(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(stream, "SUBSCRIBE_DEADLINE_SECONDS", 0.01)
    caplog.set_level(logging.WARNING, logger="lattice_cop.sources.aisstream")
    stuck = FakeConnection([frame(position())], send_delay=5)

    _, sleep, stats = await run_scripted([stuck])

    assert stuck.sent == []
    assert stats.connections_opened == 0
    assert stats.total_messages == 0
    assert sleep.delays == [2.0]
    assert caplog.records[-1].reason.startswith("TimeoutError")


async def test_connection_loss_is_logged_without_the_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="lattice_cop.sources.aisstream")

    await run_scripted(
        [OSError("refused for fake-aisstream-key"), FakeConnection([frame(position())])]
    )

    lost = [r for r in caplog.records if r.getMessage().startswith("AISStream connection lost")]
    assert [record.reason for record in lost] == [
        "OSError: refused for [redacted]",
        "closed by server",
    ]
    assert [record.retry_in_seconds for record in lost] == [2.0, 2.0]
    assert [record.attempt for record in lost] == [1, 1]
    assert "fake-aisstream-key" not in caplog.text
    # Logs carry counts and connection state only, never vessel data.
    assert "999000001" not in caplog.text
    assert "SYNTHETIC ONE" not in caplog.text


async def test_counts_are_logged_every_interval(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="lattice_cop.sources.aisstream")
    stats = stream.StreamStats()
    count(position(), stats)
    sleep = FakeSleep(limit=3)

    with pytest.raises(StopLoopError):
        await stream.log_stats(stats, sleep=sleep)

    assert sleep.delays == [60.0, 60.0, 60.0]
    records = [r for r in caplog.records if r.getMessage() == "AISStream message counts"]
    assert [record.messages["PositionReport"] for record in records] == [1, 0]
    assert [record.total_messages for record in records] == [1, 1]


# --- start and stop ---


class IdleConnection(FakeConnection):
    """Sends its frames, then stays open until the task is cancelled."""

    async def _receive(self) -> AsyncIterator[str | bytes]:
        for item in self.frames:
            yield item
        await asyncio.Event().wait()


async def test_runs_until_the_stop_event_is_set(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="lattice_cop.sources.aisstream")
    stop = asyncio.Event()
    received: list[dict[str, Any]] = []

    def on_message(message: dict[str, Any]) -> None:
        received.append(message)
        stop.set()

    connector = FakeConnector([IdleConnection([frame(position())])])
    await asyncio.wait_for(
        stream.run_until_stopped(
            FAKE_KEY,
            AOI,
            stop,
            on_message=on_message,
            connector=connector,
            url="wss://test.invalid",
        ),
        timeout=5,
    )

    assert connector.urls == ["wss://test.invalid"]
    assert len(received) == 1
    stopped = caplog.records[-1]
    assert stopped.getMessage() == "AISStream client stopped"
    assert stopped.total_messages == 1
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("ais-")]


async def test_an_unexpected_failure_is_raised_instead_of_hanging() -> None:
    def broken(_message: dict[str, Any]) -> None:
        msg = "handler bug"
        raise RuntimeError(msg)

    connector = FakeConnector([IdleConnection([frame(position())])])
    with pytest.raises(RuntimeError, match="handler bug"):
        await asyncio.wait_for(
            stream.run_until_stopped(
                FAKE_KEY, AOI, asyncio.Event(), on_message=broken, connector=connector
            ),
            timeout=5,
        )


# --- the real WebSocket library against a mock server on loopback ---


async def test_recovers_from_a_forced_disconnect_against_a_local_mock_server() -> None:
    subscriptions: list[dict[str, Any]] = []
    extensions: list[list[str]] = []

    async def mock_aisstream(connection: ServerConnection) -> None:
        raw = await asyncio.wait_for(connection.recv(), stream.SUBSCRIBE_DEADLINE_SECONDS)
        subscriptions.append(json.loads(raw))
        extensions.append([extension.name for extension in connection.protocol.extensions])
        await connection.send(frame(confirmation()))
        await connection.send(frame(position()))
        if len(subscriptions) == 1:
            # Forced disconnect: drop the first connection with an error code.
            await connection.close(code=1011)
            return
        await connection.wait_closed()

    received: list[dict[str, Any]] = []
    recovered = asyncio.Event()

    def on_message(message: dict[str, Any]) -> None:
        received.append(message)
        if len(received) == 2:
            recovered.set()

    delays: list[float] = []

    async def no_wait(delay: float) -> None:
        delays.append(delay)

    stats = stream.StreamStats()
    async with serve(mock_aisstream, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        task = asyncio.create_task(
            stream.run_stream(
                FAKE_KEY,
                AOI,
                stats=stats,
                on_message=on_message,
                sleep=no_wait,
                url=f"ws://127.0.0.1:{port}",
            )
        )
        await asyncio.wait_for(recovered.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert subscriptions == [stream.build_subscription(FAKE_KEY, AOI)] * 2
    assert extensions == [["permessage-deflate"]] * 2
    assert stats.connections_opened == 2
    assert stats.positions_in_aoi == 2
    assert len(delays) == 1
    assert stream.BACKOFF_MIN_SECONDS <= delays[0] <= stream.BACKOFF_MAX_SECONDS
