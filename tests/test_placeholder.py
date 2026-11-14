# SPDX-License-Identifier: Apache-2.0
"""Phase 0 placeholder tests: the package imports and the CLI stubs fail loudly."""

from collections.abc import Callable
from typing import NoReturn

import pytest

import lattice_cop
from lattice_cop import cli


def test_version_is_set() -> None:
    assert lattice_cop.__version__


def test_lattice_sdk_imports() -> None:
    """The Lattice SDK must install and import on this Python version."""
    from anduril import Lattice  # noqa: PLC0415

    assert Lattice is not None


@pytest.mark.parametrize(
    ("command", "name"),
    [
        (cli.ais_ingest, "ais-ingest"),
        (cli.adsb_ingest, "adsb-ingest"),
        (cli.sdr_check, "sdr-check"),
    ],
)
def test_cli_stubs_exit_with_not_implemented(
    command: Callable[[], NoReturn], name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        command()
    assert excinfo.value.code == cli.EXIT_NOT_IMPLEMENTED
    assert name in capsys.readouterr().err
