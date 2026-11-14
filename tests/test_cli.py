# SPDX-License-Identifier: Apache-2.0
"""CLI entry points: placeholders fail loudly, and the smoke test reports cleanly."""

import json
import logging
from collections.abc import Callable, Iterator
from typing import NoReturn

import httpx
import pytest
import respx

import lattice_cop
from lattice_cop import cli
from tests.conftest import FAKE_ENV_TOKEN, FAKE_HOST, FAKE_SANDBOX_TOKEN

ENTITIES_URL = f"https://{FAKE_HOST}/api/v1/entities"


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Put the root logger back after a command reconfigures it."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


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


def test_smoke_test_reports_bad_config_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    with pytest.raises(SystemExit) as excinfo:
        cli.smoke_test()
    assert excinfo.value.code == cli.EXIT_FAILED
    assert "LATTICE_URL" in capsys.readouterr().err


@pytest.mark.usefixtures("token_env", "restore_logging")
@respx.mock
def test_smoke_test_publishes_and_logs_the_expiry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    publish = respx.put(ENTITIES_URL).mock(
        return_value=httpx.Response(200, json={"entityId": "lattice-cop-ais-999000001"})
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.smoke_test()

    assert excinfo.value.code == cli.EXIT_OK
    body = json.loads(publish.calls.last.request.content)
    assert body["entityId"] == "lattice-cop-ais-999000001"
    assert body["ontology"]["template"] == "TEMPLATE_TRACK"
    assert body["location"]["position"]["altitudeHaeMeters"] == 0.0
    assert "expiryTime" in body

    out = capsys.readouterr().out
    record = json.loads(out.strip().splitlines()[-1])
    assert record["message"] == "smoke test vessel published"
    assert record["entity_id"] == "lattice-cop-ais-999000001"
    assert FAKE_ENV_TOKEN not in out
    assert FAKE_SANDBOX_TOKEN not in out


@pytest.mark.usefixtures("token_env", "restore_logging")
@respx.mock
def test_smoke_test_logs_api_errors_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    respx.put(ENTITIES_URL).mock(return_value=httpx.Response(401, json={"message": "bad token"}))

    with pytest.raises(SystemExit) as excinfo:
        cli.smoke_test()

    assert excinfo.value.code == cli.EXIT_FAILED
    out = capsys.readouterr().out
    record = json.loads(out.strip().splitlines()[-1])
    assert record["level"] == "ERROR"
    assert record["status_code"] == 401
    assert FAKE_ENV_TOKEN not in out
    assert FAKE_SANDBOX_TOKEN not in out
