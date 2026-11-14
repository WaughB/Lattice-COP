# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points: ``ais-ingest``, ``adsb-ingest``, ``sdr-check``, ``smoke-test``.

The ingest commands and ``sdr-check`` are placeholders until their build phases
land (see docs/PLAN.md). Each placeholder exits with status 2 so a container
started too early fails loudly instead of looking healthy.
"""

import logging
import sys
from typing import NoReturn

import httpx
from anduril.core.api_error import ApiError

from lattice_cop import __version__, smoke
from lattice_cop.config import ConfigError, load_settings
from lattice_cop.lattice.client import build_client
from lattice_cop.logs import configure_logging

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


def ais_ingest() -> NoReturn:
    """Run the AIS pipeline: AISStream to Lattice (Phase 5)."""
    _not_implemented("ais-ingest", 5)


def adsb_ingest() -> NoReturn:
    """Run the ADS-B pipeline: readsb or ADS-B Exchange to Lattice (Phase 5)."""
    _not_implemented("adsb-ingest", 5)


def sdr_check() -> NoReturn:
    """Run the receiver signal gate and print a pass/fail report (Phase 3)."""
    _not_implemented("sdr-check", 3)


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
