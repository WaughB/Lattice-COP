# SPDX-License-Identifier: Apache-2.0
"""CLI entry points: placeholders fail loudly; real commands report cleanly."""

import asyncio
import json
import logging
import os
import signal
from collections.abc import Callable, Iterator
from typing import Any, NoReturn

import httpx
import pytest
import respx
from pydantic import SecretStr

import lattice_cop
from lattice_cop import cli, sdrcheck
from lattice_cop.geo import BoundingBox
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


@pytest.mark.parametrize(("command", "name"), [(cli.adsb_ingest, "adsb-ingest")])
def test_cli_stubs_exit_with_not_implemented(
    command: Callable[[], NoReturn], name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        command()
    assert excinfo.value.code == cli.EXIT_NOT_IMPLEMENTED
    assert name in capsys.readouterr().err


def test_ais_ingest_reports_bad_config_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    with pytest.raises(SystemExit) as excinfo:
        cli.ais_ingest()
    assert excinfo.value.code == cli.EXIT_FAILED
    assert "LATTICE_URL" in capsys.readouterr().err


@pytest.mark.usefixtures("token_env")
def test_ais_ingest_needs_the_aisstream_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    with pytest.raises(SystemExit) as excinfo:
        cli.ais_ingest()
    assert excinfo.value.code == cli.EXIT_FAILED
    assert "AISSTREAM_API_KEY" in capsys.readouterr().err


@pytest.mark.usefixtures("token_env", "restore_logging")
def test_ais_ingest_runs_the_stream_until_sigterm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    monkeypatch.setenv("AISSTREAM_API_KEY", "fake-aisstream-key")
    calls: list[tuple[SecretStr, BoundingBox]] = []

    async def fake_run(api_key: SecretStr, aoi: BoundingBox, stop: asyncio.Event) -> None:
        calls.append((api_key, aoi))
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(stop.wait(), timeout=5)

    monkeypatch.setattr(cli.aisstream, "run_until_stopped", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        cli.ais_ingest()

    assert excinfo.value.code == cli.EXIT_OK
    assert len(calls) == 1
    api_key, aoi = calls[0]
    assert api_key.get_secret_value() == "fake-aisstream-key"
    assert aoi == BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)
    out = capsys.readouterr().out
    record = json.loads(out.strip().splitlines()[0])
    assert record["message"].startswith("ais-ingest starting")
    assert record["aoi"] == [[27.40, -83.00], [28.20, -82.25]]
    assert "fake-aisstream-key" not in out


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


@pytest.mark.usefixtures("token_env", "restore_logging")
@respx.mock
def test_smoke_test_reports_an_unreachable_environment_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    respx.put(ENTITIES_URL).mock(side_effect=httpx.ConnectError("Connection reset by peer"))

    with pytest.raises(SystemExit) as excinfo:
        cli.smoke_test()

    assert excinfo.value.code == cli.EXIT_FAILED
    captured = capsys.readouterr()
    record = json.loads(captured.out.strip().splitlines()[-1])
    assert record["message"] == "smoke test could not reach Lattice"
    assert record["error"] == "ConnectError"
    assert record["host"] == FAKE_HOST
    assert "Traceback" not in captured.out + captured.err
    assert FAKE_ENV_TOKEN not in captured.out
    assert FAKE_SANDBOX_TOKEN not in captured.out


# --- sdr-check ---

RECEIVER_URL = "http://readsb/data/aircraft.json"


class FakeClock:
    """A clock that only moves when the signal gate sleeps."""

    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def sdr_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> FakeClock:
    """Receiver settings with a synthetic antenna location, and a fake clock for the gate."""
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    monkeypatch.setenv("RECEIVER_LAT", "27.90")
    monkeypatch.setenv("RECEIVER_LON", "-82.50")
    monkeypatch.setenv("SDR_CHECK_MIN_AIRCRAFT", "2")
    clock = FakeClock()
    real_run = sdrcheck.run_check

    def fast_run(*args: Any, **kwargs: Any) -> float:
        return real_run(*args, clock=clock, sleep=clock.sleep, **kwargs)

    monkeypatch.setattr(cli.sdrcheck, "run_check", fast_run)
    return clock


def aircraft_json(
    clock: FakeClock, *positions: tuple[float, float]
) -> Callable[[httpx.Request], httpx.Response]:
    """Answer each request with a synthetic aircraft.json stamped with the fake time."""

    def respond(_request: httpx.Request) -> httpx.Response:
        aircraft = [
            {"hex": f"ffff{index:02x}", "lat": lat, "lon": lon, "seen_pos": 0.4}
            for index, (lat, lon) in enumerate(positions, start=1)
        ]
        return httpx.Response(
            200, json={"now": clock.now, "messages": int(clock.now * 20), "aircraft": aircraft}
        )

    return respond


def test_sdr_check_needs_the_receiver_location(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("no-dotenv"))
    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check([])
    assert excinfo.value.code == cli.EXIT_FAILED
    assert "LATTICE_URL" in capsys.readouterr().err

    request.getfixturevalue("token_env")
    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check([])
    assert excinfo.value.code == cli.EXIT_FAILED
    assert "RECEIVER_LAT" in capsys.readouterr().err


@pytest.mark.usefixtures("token_env", "restore_logging")
@respx.mock
def test_sdr_check_passes_and_prints_a_report_without_the_location(
    sdr_env: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    route = respx.get(RECEIVER_URL).mock(
        side_effect=aircraft_json(sdr_env, (27.75, -82.55), (27.60, -82.70), (28.90, -82.50))
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check(["--minutes", "2"])

    assert excinfo.value.code == cli.EXIT_OK
    assert route.call_count == 120
    out = capsys.readouterr().out
    assert "Result: PASS" in out
    assert out.count("[PASS]") == 4
    progress = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert [record["message"] for record in progress] == [
        "sdr-check starting",
        "sdr-check progress",
    ]
    assert progress[1]["aircraft_in_aoi"] == 2
    assert progress[1]["farthest_nm"] == 60
    assert "27.9" not in out
    assert "-82.5" not in out


@pytest.mark.usefixtures("token_env", "restore_logging")
@respx.mock
def test_sdr_check_fails_when_too_few_aircraft_are_seen(
    sdr_env: FakeClock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SDR_CHECK_MINUTES", "0.5")
    route = respx.get(RECEIVER_URL).mock(side_effect=aircraft_json(sdr_env, (28.90, -82.50)))

    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check([])

    assert excinfo.value.code == cli.EXIT_FAILED
    assert route.call_count == 30
    out = capsys.readouterr().out
    assert "[FAIL] Unique aircraft with a position inside the AOI" in out
    assert out.rstrip().endswith("Result: FAIL")


@pytest.mark.usefixtures("token_env", "restore_logging", "sdr_env")
@respx.mock
def test_sdr_check_explains_an_unreachable_receiver(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(RECEIVER_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check(["--minutes", "5"])

    assert excinfo.value.code == cli.EXIT_FAILED
    captured = capsys.readouterr()
    assert "could not read aircraft.json from ADSB_RECEIVER_URL" in captured.err
    assert "docker compose --profile sdr up -d readsb" in captured.err
    assert "Traceback" not in captured.out + captured.err
    assert "Result:" not in captured.out


@pytest.mark.usefixtures("token_env", "restore_logging", "sdr_env")
def test_sdr_check_stopped_early_reports_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(*_args: Any, **_kwargs: Any) -> float:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.sdrcheck, "run_check", interrupted)

    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check([])

    assert excinfo.value.code == cli.EXIT_FAILED
    assert "stopped early" in capsys.readouterr().out


@pytest.mark.usefixtures("token_env", "sdr_env")
def test_sdr_check_rejects_a_zero_duration(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.sdr_check(["--minutes", "0"])
    assert excinfo.value.code == 2
    assert "--minutes must be greater than 0" in capsys.readouterr().err
