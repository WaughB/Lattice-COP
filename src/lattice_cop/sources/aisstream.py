# SPDX-License-Identifier: Apache-2.0
"""AISStream WebSocket client: connect, subscribe, count messages, reconnect.

One connection only (the account limit is 3). The subscription goes out as soon
as the socket opens, because AISStream closes a connection that has not
subscribed within 3 seconds. A lost connection is retried with exponential
backoff and jitter, from 2 s up to 60 s.

Nothing here stores or logs vessel data: the logs carry counts only.
"""

import asyncio
import json
import logging
import random
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from pydantic import SecretStr
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from lattice_cop.geo import BoundingBox

AISSTREAM_URL: Final = "wss://stream.aisstream.io/v0/stream"

POSITION_TYPES: Final = frozenset({"PositionReport", "StandardClassBPositionReport"})
MESSAGE_TYPES: Final = (
    "PositionReport",
    "StandardClassBPositionReport",
    "ShipStaticData",
    "StaticDataReport",
)
CONFIRMATION_TYPE: Final = "SubscriptionConfirmation"
OTHER_TYPE: Final = "other"

SUBSCRIBE_DEADLINE_SECONDS: Final = 3.0
OPEN_TIMEOUT_SECONDS: Final = 10.0
BACKOFF_MIN_SECONDS: Final = 2.0
BACKOFF_MAX_SECONDS: Final = 60.0
STATS_INTERVAL_SECONDS: Final = 60.0

_MAX_BACKOFF_DOUBLINGS: Final = 10
_MAX_ERROR_TEXT: Final = 200

log = logging.getLogger("lattice_cop.sources.aisstream")

MessageHandler = Callable[[dict[str, Any]], None]
Sleep = Callable[[float], Awaitable[None]]


class Connection(Protocol):
    """The part of a WebSocket connection this module uses."""

    async def send(self, message: str) -> None:
        """Send one text frame."""
        ...  # pragma: no cover - protocol stub

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        """Yield received frames until the connection closes."""
        ...  # pragma: no cover - protocol stub


Connector = Callable[[str], AbstractAsyncContextManager[Connection]]


def open_connection(url: str) -> AbstractAsyncContextManager[Connection]:
    """Open a WebSocket to ``url``, offering permessage-deflate compression."""
    return connect(url, compression="deflate", open_timeout=OPEN_TIMEOUT_SECONDS)


@dataclass
class StreamStats:
    """Message counters. Interval counts reset on ``drain``; totals keep running."""

    by_type: Counter[str] = field(default_factory=Counter)
    positions_in_aoi: int = 0
    positions_outside_aoi: int = 0
    invalid_frames: int = 0
    server_errors: int = 0
    connections_opened: int = 0
    total_messages: int = 0
    total_positions_in_aoi: int = 0

    def drain(self) -> dict[str, Any]:
        """Return the counts since the last call as log fields, then reset them."""
        fields: dict[str, Any] = {
            "messages": {name: self.by_type.get(name, 0) for name in (*MESSAGE_TYPES, OTHER_TYPE)},
            "positions_in_aoi": self.positions_in_aoi,
            "positions_outside_aoi": self.positions_outside_aoi,
            "invalid_frames": self.invalid_frames,
            "server_errors": self.server_errors,
            "connections_opened": self.connections_opened,
            "total_messages": self.total_messages,
            "total_positions_in_aoi": self.total_positions_in_aoi,
        }
        self.by_type.clear()
        self.positions_in_aoi = 0
        self.positions_outside_aoi = 0
        self.invalid_frames = 0
        self.server_errors = 0
        return fields


def build_subscription(api_key: SecretStr, aoi: BoundingBox) -> dict[str, Any]:
    """Return the AISStream subscription message for one area and our message types."""
    return {
        "APIKey": api_key.get_secret_value(),
        "BoundingBoxes": [aoi.corners()],
        "FilterMessageTypes": list(MESSAGE_TYPES),
    }


def backoff_delay(attempt: int, rng: Callable[[], float] = random.random) -> float:
    """Return how long to wait before reconnect number ``attempt`` (0 is the first).

    The ceiling doubles from 2 s to 60 s. The delay is a random point in the top
    half of the ceiling, and never less than 2 s.
    """
    doublings = min(max(attempt, 0), _MAX_BACKOFF_DOUBLINGS)
    ceiling = min(BACKOFF_MAX_SECONDS, BACKOFF_MIN_SECONDS * 2.0**doublings)
    return max(BACKOFF_MIN_SECONDS, ceiling * (0.5 + 0.5 * rng()))


def _redact(text: str, api_key: SecretStr) -> str:
    """Shorten ``text`` for a log line and remove the API key if it appears in it."""
    secret = api_key.get_secret_value()
    cleaned = text.replace(secret, "[redacted]") if secret else text
    return cleaned[:_MAX_ERROR_TEXT]


def _number(value: object) -> float | None:
    """Return ``value`` as a float if it is a real number, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _point(source: object, lat_key: str, lon_key: str) -> tuple[float, float] | None:
    """Return ``(latitude, longitude)`` from a mapping, or ``None`` if either is missing."""
    if not isinstance(source, dict):
        return None
    latitude, longitude = _number(source.get(lat_key)), _number(source.get(lon_key))
    if latitude is None or longitude is None:
        return None
    return latitude, longitude


def extract_position(message: dict[str, Any], kind: str) -> tuple[float, float] | None:
    """Return ``(latitude, longitude)`` from a position message, or ``None``.

    The typed body under ``Message`` is preferred. ``MetaData`` is the fallback,
    in either letter case (AISStream's docs and older payloads differ).
    """
    body = message.get("Message")
    typed = body.get(kind) if isinstance(body, dict) else None
    meta = message.get("MetaData")
    return (
        _point(typed, "Latitude", "Longitude")
        or _point(meta, "Latitude", "Longitude")
        or _point(meta, "latitude", "longitude")
    )


def _decode(frame: str | bytes) -> dict[str, Any] | None:
    """Parse one frame as a JSON object, or return ``None`` if it is not one."""
    try:
        parsed = json.loads(frame)
    except ValueError:
        # Covers bad JSON and bytes that are not UTF-8.
        return None
    return parsed if isinstance(parsed, dict) else None


def _log_confirmation(message: dict[str, Any]) -> None:
    """Log the server's subscription confirmation and whether compression is on."""
    body = message.get("Message")
    compressed = isinstance(body, dict) and body.get("CompressionEnabled") is True
    if compressed:
        log.info("AISStream subscription confirmed", extra={"compression": True})
    else:
        log.warning(
            "AISStream subscription confirmed without compression; "
            "uncompressed connections are bandwidth-limited and may drop messages",
            extra={"compression": False},
        )


def handle_frame(
    frame: str | bytes,
    *,
    aoi: BoundingBox,
    stats: StreamStats,
    api_key: SecretStr,
    on_message: MessageHandler | None = None,
) -> bool:
    """Count one received frame and pass data messages to ``on_message``.

    Returns:
        True if the frame was one of the subscribed AIS message types.
    """
    message = _decode(frame)
    if message is None:
        stats.invalid_frames += 1
        return False
    if "error" in message:
        stats.server_errors += 1
        log.error(
            "AISStream reported an error",
            extra={"detail": _redact(str(message["error"]), api_key)},
        )
        return False

    kind = message.get("MessageType")
    if kind == CONFIRMATION_TYPE:
        _log_confirmation(message)
        return False
    if not isinstance(kind, str) or kind not in MESSAGE_TYPES:
        stats.by_type[OTHER_TYPE] += 1
        return False

    stats.by_type[kind] += 1
    stats.total_messages += 1
    if kind in POSITION_TYPES:
        position = extract_position(message, kind)
        if position is not None and aoi.contains(*position):
            stats.positions_in_aoi += 1
            stats.total_positions_in_aoi += 1
        else:
            stats.positions_outside_aoi += 1
    if on_message is not None:
        on_message(message)
    return True


async def run_stream(  # noqa: PLR0913 - the extra arguments are test seams
    api_key: SecretStr,
    aoi: BoundingBox,
    *,
    stats: StreamStats,
    on_message: MessageHandler | None = None,
    connector: Connector = open_connection,
    sleep: Sleep = asyncio.sleep,
    rng: Callable[[], float] = random.random,
    url: str = AISSTREAM_URL,
) -> None:
    """Stay connected to AISStream until cancelled, reconnecting after every loss.

    Args:
        api_key: AISStream API key. It is sent in the subscription and never logged.
        aoi: Area to subscribe to.
        stats: Counters updated for every frame.
        on_message: Called with each subscribed AIS message, already parsed.
        connector: Opens the WebSocket. Tests pass a fake.
        sleep: Waits between reconnects. Tests pass a fake.
        rng: Source of jitter in ``[0, 1)``.
        url: WebSocket endpoint.
    """
    subscription = json.dumps(build_subscription(api_key, aoi))
    attempt = 0
    while True:
        try:
            async with connector(url) as connection:
                async with asyncio.timeout(SUBSCRIBE_DEADLINE_SECONDS):
                    await connection.send(subscription)
                stats.connections_opened += 1
                log.info("subscribed to AISStream", extra={"message_types": list(MESSAGE_TYPES)})
                async for frame in connection:
                    if handle_frame(
                        frame, aoi=aoi, stats=stats, api_key=api_key, on_message=on_message
                    ):
                        # Data is flowing, so the next loss starts from the shortest delay.
                        attempt = 0
            reason = "closed by server"
        except (OSError, TimeoutError, WebSocketException) as error:
            reason = f"{type(error).__name__}: {_redact(str(error), api_key)}"

        delay = backoff_delay(attempt, rng)
        attempt += 1
        log.warning(
            "AISStream connection lost; reconnecting",
            extra={"reason": reason, "retry_in_seconds": round(delay, 1), "attempt": attempt},
        )
        await sleep(delay)


async def log_stats(
    stats: StreamStats,
    *,
    interval: float = STATS_INTERVAL_SECONDS,
    sleep: Sleep = asyncio.sleep,
) -> None:
    """Log message counts by type every ``interval`` seconds until cancelled."""
    while True:
        await sleep(interval)
        log.info("AISStream message counts", extra=stats.drain())


async def run_until_stopped(  # noqa: PLR0913 - the extra arguments are test seams
    api_key: SecretStr,
    aoi: BoundingBox,
    stop: asyncio.Event,
    *,
    on_message: MessageHandler | None = None,
    connector: Connector = open_connection,
    url: str = AISSTREAM_URL,
) -> None:
    """Run the stream and the 60 s counter log until ``stop`` is set.

    Raises:
        Exception: Whatever an internal task raised, if one failed unexpectedly.
    """
    stats = StreamStats()
    workers = [
        asyncio.create_task(
            run_stream(
                api_key, aoi, stats=stats, on_message=on_message, connector=connector, url=url
            ),
            name="ais-stream",
        ),
        asyncio.create_task(log_stats(stats), name="ais-stats"),
    ]
    stopper = asyncio.create_task(stop.wait(), name="ais-stop")
    done, _ = await asyncio.wait({stopper, *workers}, return_when=asyncio.FIRST_COMPLETED)
    for task in (stopper, *workers):
        task.cancel()
    await asyncio.gather(stopper, *workers, return_exceptions=True)
    log.info("AISStream client stopped", extra=stats.drain())
    for task in done - {stopper}:
        task.result()
