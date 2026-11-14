# SPDX-License-Identifier: Apache-2.0
"""Command-line entry points: ``ais-ingest``, ``adsb-ingest`` and ``sdr-check``.

The commands are placeholders until their build phases land (see docs/PLAN.md).
Each one exits with status 2 so a container started too early fails loudly
instead of looking healthy.
"""

import sys
from typing import NoReturn

from lattice_cop import __version__

EXIT_NOT_IMPLEMENTED = 2


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
