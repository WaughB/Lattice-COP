# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points: ``ais-ingest``, ``adsb-ingest``, ``sdr-check``, ``smoke-test``.

``adsb-ingest`` is a placeholder until its build phase lands (see docs/PLAN.md).
It exits with status 2 so a container started too early fails loudly instead of
looking healthy.
"""

import argparse
import asyncio
import logging
import signal
import sys
import time
from typing import NoReturn

import httpx
from anduril.core.api_error import ApiError
from pydantic import SecretStr

from lattice_cop import __version__, sdrcheck, smoke
from lattice_cop.config import ConfigError, load_settings
from lattice_cop.geo import BoundingBox
from lattice_cop.lattice.client import build_client
from lattice_cop.logs import configure_logging
from lattice_cop.sources import aisstream, readsb

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_IMPLEMENTED = 2

log = logging.getLogger("lattice_cop.cli")


def _not_implemented(command: str, phase: int) -> NoReturn:
    """Report that a command is not built yet and exit.

    Args:
        command: Name of the console script that was run.
        phase: Build phase in docs/PLAN.md that delivers the command.
    """
    sys.stderr.write(
        f"lattice-cop {__version__}: '{command}' is not implemented yet "
        f"(arrives in Phase {phase}; see docs/PLAN.md)\n"
    )
    raise SystemExit(EXIT_NOT_IMPLEMENTED)


async def _run_ais(api_key: SecretStr, aoi: BoundingBox) -> None:
    """Run the AISStream client until the process gets SIGINT or SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await aisstream.run_until_stopped(api_key, aoi, stop)


def ais_ingest() -> NoReturn:
    """Run the AIS pipeline.

    For now it connects to AISStream and logs message counts every 60 s.
    Cleaning arrives in Phase 4 and publishing to Lattice in Phase 5.
    """
    try:
        settings = load_settings()
        api_key = settings.require_aisstream_api_key()
    except ConfigError as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(EXIT_FAILED) from None

    configure_logging(settings.log_level)
    log.info(
        "ais-ingest starting (connection and counts only; nothing is published yet)",
        extra={"version": __version__, "aoi": settings.aoi.corners()},
    )
    asyncio.run(_run_ais(api_key, settings.aoi))
    raise SystemExit(EXIT_OK)


def adsb_ingest() -> NoReturn:
    """Run the ADS-B pipeline: readsb or ADS-B Exchange to Lattice (Phase 5)."""
    _not_implemented("adsb-ingest", 5)


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
