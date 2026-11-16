# SPDX-License-Identifier: Apache-2.0
"""The two ingest pipelines, end to end: source, clean, convert, publish.

``run_ais`` streams AISStream messages; ``run_adsb`` polls readsb's
aircraft.json once a second. Each runs until its stop event is set, logs its
counters every 60 s, and on shutdown simply stops publishing so tracks expire
by themselves. Nothing is deleted from Lattice.
"""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from tampa_cop.clean.adsb import AdsbCleaner, AdsbRules
from tampa_cop.clean.ais import AisCleaner, AisRules
from tampa_cop.clean.throttle import Throttle
from tampa_cop.config import Settings
from tampa_cop.lattice.publisher import EntitiesClient, Publisher
from tampa_cop.sources import airlines, aisstream, readsb

COUNTS_INTERVAL_SECONDS: Final = 60.0
ADSB_POLL_SECONDS: Final = 1.0
AIRLINE_RETRY_SECONDS: Final = 60.0
AIRLINE_REFRESH_SECONDS: Final = 86_400.0
"""The table only changes when the receiver image does, so one look a day is plenty."""

FAILED_POLLS: Final = "failed_polls"
UNCHANGED_POLLS: Final = "unchanged_polls"
POLLS: Final = "polls"

log = logging.getLogger("tampa_cop.ingest")

Sleep = Callable[[float], Awaitable[None]]


async def supervise(stop: asyncio.Event, *work: Coroutine[Any, Any, None]) -> None:
    """Run coroutines side by side until ``stop`` is set, then cancel them.

    Raises:
        Exception: Whatever a coroutine raised, if one failed unexpectedly. A
            pipeline that dies must take the process down, not hang half-alive.
    """
    workers = [asyncio.create_task(item) for item in work]
    stopper = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({stopper, *workers}, return_when=asyncio.FIRST_COMPLETED)
    for task in (stopper, *workers):
        task.cancel()
    await asyncio.gather(stopper, *workers, return_exceptions=True)
    for task in done - {stopper}:
        task.result()


async def _log_counts(
    name: str,
    snapshot: Callable[[], dict[str, Any]],
    *,
    interval: float = COUNTS_INTERVAL_SECONDS,
    sleep: Sleep = asyncio.sleep,
) -> None:
    """Log a service's counters every ``interval`` seconds until cancelled."""
    while True:
        await sleep(interval)
        log.info(f"{name} counts", extra=snapshot())


async def run_ais(  # noqa: PLR0913 - the extra arguments are test seams
    settings: Settings,
    entities: EntitiesClient,
    stop: asyncio.Event,
    *,
    connector: aisstream.Connector = aisstream.open_connection,
    url: str = aisstream.AISSTREAM_URL,
    sleep: Sleep = asyncio.sleep,
) -> None:
    """Run the AIS pipeline until ``stop`` is set.

    Args:
        settings: Validated settings.
        entities: The SDK's async entities client.
        stop: Set it to shut the pipeline down.
        connector: Opens the WebSocket. Tests pass a fake.
        url: AISStream endpoint.
        sleep: Waits between reconnects and count logs. Tests pass a fake.
    """
    api_key = settings.require_aisstream_api_key()
    stats = aisstream.StreamStats()
    cleaner = AisCleaner(AisRules.from_settings(settings))
    publisher = Publisher(
        entities,
        expiry_seconds=settings.ais_expiry_seconds,
        throttle=Throttle(settings.ais_throttle_seconds),
        concurrency=settings.publish_concurrency,
    )

    def on_message(message: dict[str, Any]) -> None:
        track = cleaner.clean(message, datetime.now(UTC))
        if track is not None:
            # A new name or new static details go out at once, throttle or not.
            publisher.submit(track, (track.name, track.description, track.callsign))

    def counts() -> dict[str, Any]:
        cleaner.prune(datetime.now(UTC))
        publisher.prune()
        return {
            "stream": stats.drain(),
            "clean": dict(cleaner.counts),
            "publish": dict(publisher.counts),
            "vessels_tracked": cleaner.tracked,
            "backlog": publisher.backlog,
        }

    try:
        await supervise(
            stop,
            aisstream.run_stream(
                api_key,
                settings.aoi,
                stats=stats,
                on_message=on_message,
                connector=connector,
                url=url,
                sleep=sleep,
            ),
            publisher.run(),
            _log_counts("ais-ingest", counts, sleep=sleep),
        )
    finally:
        log.info("ais-ingest stopped; tracks will expire in Lattice", extra=counts())


async def _poll_readsb(  # noqa: PLR0913 - one argument per collaborator
    url: str,
    cleaner: AdsbCleaner,
    publisher: Publisher,
    polls: Counter[str],
    *,
    client: httpx.AsyncClient,
    sleep: Sleep,
    monotonic: Callable[[], float],
) -> None:
    """Fetch aircraft.json once a second and hand cleaned tracks to the publisher."""
    last_now: float | None = None
    start, ticks = monotonic(), 0
    while True:
        polls[POLLS] += 1
        try:
            snapshot = await readsb.fetch_snapshot_async(client, url)
        except readsb.ReadsbError:
            polls[FAILED_POLLS] += 1
        else:
            if last_now is not None and snapshot.now <= last_now:
                # readsb has not written a new file since the last poll.
                polls[UNCHANGED_POLLS] += 1
            else:
                last_now = snapshot.now
                for track in cleaner.clean_snapshot(snapshot):
                    publisher.submit(track)
        ticks += 1
        await sleep(max(0.0, start + ticks * ADSB_POLL_SECONDS - monotonic()))


async def _keep_airlines(
    url: str, cleaner: AdsbCleaner, *, client: httpx.AsyncClient, sleep: Sleep
) -> None:
    """Give the cleaner the receiver's airline table, retrying until it answers.

    Aircraft are published without airline names in the meantime.
    """
    warned = announced = False
    while True:
        try:
            cleaner.airlines = await airlines.fetch_airlines(client, url)
        except airlines.AirlineTableError as error:
            if not warned:
                log.warning(
                    "airline names are not available; retrying", extra={"reason": str(error)}
                )
                warned = True
            await sleep(AIRLINE_RETRY_SECONDS)
        else:
            if not announced:
                log.info(
                    "airline names loaded from the receiver",
                    extra={"airlines": len(cleaner.airlines)},
                )
                announced = True
            warned = False
            await sleep(AIRLINE_REFRESH_SECONDS)


async def run_adsb(  # noqa: PLR0913 - the extra arguments are test seams
    settings: Settings,
    entities: EntitiesClient,
    stop: asyncio.Event,
    *,
    client: httpx.AsyncClient | None = None,
    sleep: Sleep = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Run the ADS-B pipeline against readsb until ``stop`` is set.

    Args:
        settings: Validated settings.
        entities: The SDK's async entities client.
        stop: Set it to shut the pipeline down.
        client: HTTP client for readsb. One is created if not given.
        sleep: Waits between polls and count logs. Tests pass a fake.
        monotonic: Clock that paces the polls.
    """
    cleaner = AdsbCleaner(AdsbRules.from_settings(settings))
    publisher = Publisher(
        entities,
        expiry_seconds=settings.adsb_expiry_seconds,
        throttle=Throttle(settings.adsb_throttle_seconds),
        concurrency=settings.publish_concurrency,
    )
    polls: Counter[str] = Counter()

    def counts() -> dict[str, Any]:
        cleaner.prune(datetime.now(UTC).timestamp())
        publisher.prune()
        return {
            "polls": dict(polls),
            "clean": dict(cleaner.counts),
            "publish": dict(publisher.counts),
            "aircraft_tracked": cleaner.tracked,
            "backlog": publisher.backlog,
        }

    owned = client is None
    http = client or httpx.AsyncClient()
    try:
        await supervise(
            stop,
            _poll_readsb(
                settings.adsb_receiver_url,
                cleaner,
                publisher,
                polls,
                client=http,
                sleep=sleep,
                monotonic=monotonic,
            ),
            _keep_airlines(settings.adsb_receiver_url, cleaner, client=http, sleep=sleep),
            publisher.run(),
            _log_counts("adsb-ingest", counts, sleep=sleep),
        )
    finally:
        if owned:
            await http.aclose()
        log.info("adsb-ingest stopped; tracks will expire in Lattice", extra=counts())
