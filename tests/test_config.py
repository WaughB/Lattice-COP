# SPDX-License-Identifier: Apache-2.0
"""Settings: defaults, validation, and error messages that name variables without leaking values."""

from pathlib import Path

import pytest

from tampa_cop.config import ConfigError, load_settings, min_poll_seconds
from tests.conftest import FAKE_CLIENT_SECRET, FAKE_ENV_TOKEN, FAKE_HOST, FAKE_SANDBOX_TOKEN


def load() -> None:
    load_settings(env_file=None)


@pytest.mark.usefixtures("token_env")
def test_defaults_match_the_tampa_bay_aoi() -> None:
    settings = load_settings(env_file=None)
    assert settings.lattice_url == FAKE_HOST
    assert (settings.aoi_south, settings.aoi_west) == (27.40, -83.00)
    assert (settings.aoi_north, settings.aoi_east) == (28.20, -82.25)
    assert (settings.adsb_center_lat, settings.adsb_center_lon) == (27.9755, -82.5332)
    assert settings.adsb_radius_nm == 60
    assert settings.adsb_source == "receiver"
    assert settings.ais_expiry_seconds == 600
    assert settings.adsb_expiry_seconds == 60
    assert settings.ais_throttle_seconds == 10
    assert settings.adsb_throttle_seconds == 2
    assert settings.geoid_offset_m == -26.7
    assert settings.publish_concurrency == 2
    assert settings.log_level == "INFO"


def test_missing_required_values_name_the_variables() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load()
    message = str(excinfo.value)
    assert "LATTICE_URL" in message
    assert "LATTICE_SANDBOXES_TOKEN" in message


@pytest.mark.usefixtures("token_env")
@pytest.mark.parametrize(
    "value",
    [f"https://{FAKE_HOST}", f"https://{FAKE_HOST}/", f"http://{FAKE_HOST}", f"  {FAKE_HOST}  "],
)
def test_lattice_url_accepts_a_scheme_and_keeps_the_hostname(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("LATTICE_URL", value)
    assert load_settings(env_file=None).lattice_url == FAKE_HOST


@pytest.mark.usefixtures("token_env")
@pytest.mark.parametrize("value", ["https://", f"https://{FAKE_HOST}/api/v1", "two words"])
def test_lattice_url_rejects_non_hostnames(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LATTICE_URL", value)
    with pytest.raises(ConfigError, match="LATTICE_URL"):
        load()


@pytest.mark.usefixtures("token_env")
def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose passes ``KEY=`` lines through as empty strings; they must not break parsing."""
    monkeypatch.setenv("AOI_SOUTH", "")
    monkeypatch.setenv("LATTICE_CLIENT_ID", "")
    monkeypatch.setenv("RECEIVER_LAT", "")
    settings = load_settings(env_file=None)
    assert settings.aoi_south == 27.40
    assert settings.lattice_client_id is None
    assert settings.receiver_lat is None


@pytest.mark.usefixtures("client_credentials_env")
def test_client_credentials_are_accepted() -> None:
    settings = load_settings(env_file=None)
    assert settings.lattice_environment_token is None
    assert settings.lattice_client_id == "fake-client-id"


def test_no_lattice_credentials_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LATTICE_URL", FAKE_HOST)
    monkeypatch.setenv("LATTICE_SANDBOXES_TOKEN", FAKE_SANDBOX_TOKEN)
    with pytest.raises(ConfigError, match="LATTICE_ENVIRONMENT_TOKEN"):
        load()


@pytest.mark.usefixtures("token_env")
def test_token_and_client_credentials_together_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LATTICE_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("LATTICE_CLIENT_SECRET", FAKE_CLIENT_SECRET)
    with pytest.raises(ConfigError, match="not both"):
        load()


def test_half_a_client_credential_pair_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LATTICE_URL", FAKE_HOST)
    monkeypatch.setenv("LATTICE_SANDBOXES_TOKEN", FAKE_SANDBOX_TOKEN)
    monkeypatch.setenv("LATTICE_CLIENT_ID", "fake-client-id")
    with pytest.raises(ConfigError, match="must be set together"):
        load()


@pytest.mark.usefixtures("token_env")
@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("AOI_SOUTH", "29", "AOI_SOUTH must be less than AOI_NORTH"),
        ("AOI_WEST", "-82", "AOI_WEST must be less than AOI_EAST"),
        ("AOI_NORTH", "95", "AOI_NORTH"),
        ("ADSB_RADIUS_NM", "0", "ADSB_RADIUS_NM"),
        ("ADSB_SOURCE", "radar", "ADSB_SOURCE"),
        ("AIS_EXPIRY_SECONDS", "soon", "AIS_EXPIRY_SECONDS"),
        ("LOG_LEVEL", "LOUD", "LOG_LEVEL"),
    ],
)
def test_invalid_values_name_the_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, expected: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError) as excinfo:
        load()
    assert expected in str(excinfo.value)


@pytest.mark.usefixtures("token_env")
def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert load_settings(env_file=None).log_level == "DEBUG"


@pytest.mark.usefixtures("token_env")
def test_secrets_never_appear_in_errors_or_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(env_file=None)
    assert FAKE_SANDBOX_TOKEN not in repr(settings)
    assert FAKE_ENV_TOKEN not in repr(settings)
    assert settings.lattice_sandboxes_token.get_secret_value() == FAKE_SANDBOX_TOKEN

    monkeypatch.setenv("LATTICE_CLIENT_SECRET", FAKE_CLIENT_SECRET)
    with pytest.raises(ConfigError) as excinfo:
        load()
    message = str(excinfo.value)
    for secret in (FAKE_SANDBOX_TOKEN, FAKE_ENV_TOKEN, FAKE_CLIENT_SECRET):
        assert secret not in message


@pytest.mark.usefixtures("token_env")
def test_adsbx_needs_a_key_a_quota_and_a_safe_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADSB_SOURCE", "adsbx")
    with pytest.raises(ConfigError, match="ADSBX_RAPIDAPI_KEY"):
        load()

    monkeypatch.setenv("ADSBX_RAPIDAPI_KEY", "fake-rapidapi-key")
    with pytest.raises(ConfigError, match="ADSBX_MONTHLY_QUOTA"):
        load()

    monkeypatch.setenv("ADSBX_MONTHLY_QUOTA", "10000")
    monkeypatch.setenv("ADSBX_POLL_SECONDS", "60")
    with pytest.raises(ConfigError, match=r"at least 259\.2"):
        load()

    monkeypatch.setenv("ADSBX_POLL_SECONDS", "260")
    assert load_settings(env_file=None).adsb_source == "adsbx"


def test_min_poll_seconds_follows_the_quota_formula() -> None:
    assert min_poll_seconds(2_592_000) == 1
    assert min_poll_seconds(10_000) == pytest.approx(259.2)


@pytest.mark.usefixtures("token_env")
def test_service_specific_requirements(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(env_file=None)
    with pytest.raises(ConfigError, match="AISSTREAM_API_KEY"):
        settings.require_aisstream_api_key()
    with pytest.raises(ConfigError, match="RECEIVER_LAT"):
        settings.require_receiver_location()

    monkeypatch.setenv("AISSTREAM_API_KEY", "fake-aisstream-key")
    monkeypatch.setenv("RECEIVER_LAT", "27.9")
    monkeypatch.setenv("RECEIVER_LON", "-82.5")
    settings = load_settings(env_file=None)
    assert settings.require_aisstream_api_key().get_secret_value() == "fake-aisstream-key"
    assert settings.require_receiver_location() == (27.9, -82.5)


def test_settings_can_be_read_from_a_dotenv_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"LATTICE_URL={FAKE_HOST}\n"
        f"LATTICE_SANDBOXES_TOKEN={FAKE_SANDBOX_TOKEN}\n"
        f"LATTICE_ENVIRONMENT_TOKEN={FAKE_ENV_TOKEN}\n"
        "LATTICE_CLIENT_ID=\n"
        "AOI_NORTH=28.5\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file=str(env_file))
    assert settings.aoi_north == 28.5
    assert settings.lattice_client_id is None
