# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points: ``ais-ingest``, ``adsb-ingest``, ``sdr-check``, ``smoke-test``.

Every command loads settings first and exits with status 1, naming the variable,
if one is missing or invalid.
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from typing import NoReturn

import httpx
from anduril.core.api_error import ApiError

from lattice_cop import __version__, ingest, sdrcheck, smoke
from lattice_cop.config import ConfigError, Settings, load_settings
from lattice_cop.lattice.client import build_async_client, build_client
from lattice_cop.logs import configure_logging
from lattice_cop.sources import readsb

EXIT_OK = 0
EXIT_FAILED = 1

log = logging.getLogger("lattice_cop.cli")


async def _run_until_signalled(pipeline: Callable[[asyncio.Event], Awaitable[None]]) -> None:
    """Run a pipeline until the process gets SIGINT or SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await pipeline(stop)


def _load_settings_or_exit() -> Settings:
    """Load settings, or print what is wrong and exit with status 1."""
    try:
        return load_settings()
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(EXIT_FAILED) from None


def ais_ingest() -> NoReturn:
    """Run the AIS pipeline: AISStream, cleaning, and publishing to Lattice."""
    settings = _load_settings_or_exit()
    try:
        settings.require_aisstream_api_key()
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(EXIT_FAILED) from None

    configure_logging(settings.log_level)
    log.info(
        "ais-ingest starting",
        extra={
            "version": __version__,
            "aoi": settings.aoi.corners(),
            "lattice": settings.lattice_url,
        },
    )
    entities = build_async_client(settings).entities
    asyncio.run(_run_until_signalled(lambda stop: ingest.run_ais(settings, entities, stop)))
    raise SystemExit(EXIT_OK)


def adsb_ingest() -> NoReturn:
    """Run the ADS-B pipeline: readsb, cleaning, and publishing to Lattice."""
    settings = _load_settings_or_exit()
    if settings.adsb_source != "receiver":
        # The receiver passed its signal gate, so the ADS-B Exchange fallback was never built.
        sys.stderr.write(
            "ADSB_SOURCE=adsbx is not supported: the ADS-B Exchange fallback is not built. "
            "Set ADSB_SOURCE=receiver.\n"
        )
        raise SystemExit(EXIT_FAILED)

    configure_logging(settings.log_level)
    log.info(
        "adsb-ingest starting",
        extra={
            "version": __version__,
            "aoi": settings.aoi.corners(),
            "lattice": settings.lattice_url,
        },
    )
    entities = build_async_client(settings).entities
    asyncio.run(_run_until_signalled(lambda stop: ingest.run_adsb(settings, entities, stop)))
    raise SystemExit(EXIT_OK)


def _log_sdr_progress(check: sdrcheck.SignalCheck, elapsed: float) -> None:
    """Log the running totals of the signal gate. Counts only."""
    log.info(
        "sdr-check progress",
        extra={
            "minutes": round(elapsed / 60, 1),
            "aircraft_in_aoi": len(check.aircraft_in_aoi),
            "farthest_nm": round(check.farthest_nm),
            "dropouts": check.dropouts,
            "restarts": check.restarts,
            "failed_polls": check.failed_polls,
        },
    )


def sdr_check(argv: list[str] | None = None) -> NoReturn:
    """Run the receiver signal gate and print a pass/fail report.

    Args:
        argv: Command-line arguments. Defaults to ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(
        prog="sdr-check",
        description="Watch readsb's aircraft.json and report whether reception is good enough.",
    )
    parser.add_argument(
        "--minutes",
        type=float,
        help="how long to watch (default: SDR_CHECK_MINUTES, 30)",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        receiver = settings.require_receiver_location()
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(EXIT_FAILED) from None
    minutes = settings.sdr_check_minutes if args.minutes is None else args.minutes
    if minutes <= 0:
        parser.error("--minutes must be greater than 0")

    configure_logging(settings.log_level)
    check = sdrcheck.SignalCheck(aoi=settings.aoi, receiver=receiver)
    thresholds = sdrcheck.Thresholds(
        min_aircraft=settings.sdr_check_min_aircraft,
        max_median_seen_pos=settings.sdr_check_max_median_seen_pos,
        min_range_nm=settings.sdr_check_min_range_nm,
    )
    log.info("sdr-check starting", extra={"minutes": minutes})
    started = time.monotonic()
    complete = True
    with httpx.Client() as client:
        try:
            sdrcheck.run_check(
                lambda: readsb.fetch_snapshot(client, settings.adsb_receiver_url),
                check,
                duration_seconds=minutes * 60,
                on_progress=_log_sdr_progress,
            )
        except readsb.ReadsbError as error:
            sys.stderr.write(
                f"sdr-check could not read aircraft.json from ADSB_RECEIVER_URL: {error}.\n"
                "Start the receiver first: docker compose --profile sdr up -d readsb\n"
            )
            raise SystemExit(EXIT_FAILED) from None
        except KeyboardInterrupt:
            complete = False

    report = check.report(thresholds, minutes=(time.monotonic() - started) / 60, complete=complete)
    sys.stdout.write(sdrcheck.format_report(report) + "\n")
    raise SystemExit(EXIT_OK if report.passed else EXIT_FAILED)


def smoke_test() -> NoReturn:
    """Publish one synthetic vessel to Lattice so the visualizer path can be checked."""
    try:
        settings = load_settings()
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(EXIT_FAILED) from None

    configure_logging(settings.log_level)
    client = build_client(settings)
    try:
        expiry = smoke.publish_smoke_entity(client.entities)
    except ApiError as error:
        # Log the status and body only: never headers, which can carry tokens.
        log.error(
            "smoke test publish failed",
            extra={
                "entity_id": smoke.SMOKE_ENTITY_ID,
                "status_code": error.status_code,
                "body": error.body,
            },
        )
        raise SystemExit(EXIT_FAILED) from None
    except httpx.TransportError as error:
        # The request never got an answer: DNS, TLS, timeout or a dropped connection.
        log.error(
            "smoke test could not reach Lattice",
            extra={
                "entity_id": smoke.SMOKE_ENTITY_ID,
                "host": settings.lattice_url,
                "error": type(error).__name__,
                "detail": str(error),
            },
        )
        raise SystemExit(EXIT_FAILED) from None

    log.info(
        "smoke test vessel published",
        extra={
            "entity_id": smoke.SMOKE_ENTITY_ID,
            "vessel_name": smoke.SMOKE_NAME,
            "latitude": smoke.SMOKE_LAT,
            "longitude": smoke.SMOKE_LON,
            "expires": expiry.isoformat(timespec="seconds"),
        },
    )
    raise SystemExit(EXIT_OK)
