# SPDX-License-Identifier: Apache-2.0
"""Settings for every Lattice-COP command, loaded from the environment or ``.env``.

Settings are validated once, at start. A missing or invalid value stops the
process with a message that names the environment variable. Secrets are held
as ``SecretStr`` and are never included in error messages.
"""

from typing import Literal, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lattice_cop.geo import BoundingBox

SECONDS_PER_30_DAYS = 2_592_000
"""Length of the month used for the ADS-B Exchange quota check (30 days)."""


class ConfigError(Exception):
    """Raised when settings are missing or invalid. The message is safe to print."""


class Settings(BaseSettings):
    """All settings, one field per environment variable (upper-cased field name)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # --- Lattice Sandboxes ---
    lattice_url: str = Field(min_length=1)
    lattice_sandboxes_token: SecretStr
    lattice_environment_token: SecretStr | None = None
    lattice_client_id: str | None = None
    lattice_client_secret: SecretStr | None = None

    # --- AISStream ---
    aisstream_api_key: SecretStr | None = None

    # --- Area of interest ---
    aoi_south: float = Field(default=27.40, ge=-90, le=90)
    aoi_west: float = Field(default=-83.00, ge=-180, le=180)
    aoi_north: float = Field(default=28.20, ge=-90, le=90)
    aoi_east: float = Field(default=-82.25, ge=-180, le=180)
    adsb_center_lat: float = Field(default=27.9755, ge=-90, le=90)
    adsb_center_lon: float = Field(default=-82.5332, ge=-180, le=180)
    adsb_radius_nm: float = Field(default=60, gt=0, le=250)

    # --- ADS-B source ---
    adsb_source: Literal["receiver", "adsbx"] = "receiver"
    adsb_receiver_url: str = "http://readsb/data/aircraft.json"
    receiver_lat: float | None = Field(default=None, ge=-90, le=90)
    receiver_lon: float | None = Field(default=None, ge=-180, le=180)
    receiver_alt_m: float | None = None
    adsbx_rapidapi_key: SecretStr | None = None
    adsbx_poll_seconds: float = Field(default=60, gt=0)
    adsbx_monthly_quota: int | None = Field(default=None, gt=0)

    # --- Receiver signal gate (sdr-check) ---
    sdr_check_minutes: float = Field(default=30, gt=0)
    sdr_check_min_aircraft: int = Field(default=20, ge=0)
    sdr_check_max_median_seen_pos: float = Field(default=5, gt=0)
    sdr_check_min_range_nm: float = Field(default=30, ge=0)

    # --- Data cleaning ---
    ais_max_age_seconds: float = Field(default=300, gt=0)
    ais_max_speed_kn: float = Field(default=50, gt=0)
    ais_allow_non_vessel_mmsi: bool = False
    ais_static_cache_seconds: float = Field(default=21600, gt=0)
    adsb_max_position_age_seconds: float = Field(default=15, gt=0)
    adsb_max_speed_kn: float = Field(default=1000, gt=0)
    adsb_allow_non_icao: bool = False
    position_jump_slack_nm: float = Field(default=0.1, ge=0)

    # --- Tuning ---
    ais_expiry_seconds: float = Field(default=600, gt=0)
    adsb_expiry_seconds: float = Field(default=60, gt=0)
    ais_throttle_seconds: float = Field(default=10, ge=0)
    adsb_throttle_seconds: float = Field(default=2, ge=0)
    geoid_offset_m: float = -26.7
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("lattice_url")
    @classmethod
    def _strip_scheme(cls, value: str) -> str:
        """Accept the endpoint with or without ``https://`` and keep the bare hostname."""
        host = value.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not host or "/" in host or " " in host:
            msg = "must be the environment hostname, such as lattice-xxxx.env.sandboxes..."
            raise ValueError(msg)
        return host

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        """Accept log levels in any letter case."""
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_area(self) -> Self:
        """The AOI box must have positive height and width."""
        if self.aoi_south >= self.aoi_north:
            msg = "AOI_SOUTH must be less than AOI_NORTH"
            raise ValueError(msg)
        if self.aoi_west >= self.aoi_east:
            msg = "AOI_WEST must be less than AOI_EAST"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_lattice_auth(self) -> Self:
        """Require exactly one way to authenticate: environment token, or client ID and secret."""
        has_token = self.lattice_environment_token is not None
        has_id = self.lattice_client_id is not None
        has_secret = self.lattice_client_secret is not None
        if has_token and (has_id or has_secret):
            msg = (
                "set LATTICE_ENVIRONMENT_TOKEN, or LATTICE_CLIENT_ID and "
                "LATTICE_CLIENT_SECRET, but not both"
            )
            raise ValueError(msg)
        if has_id != has_secret:
            msg = "LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET must be set together"
            raise ValueError(msg)
        if not has_token and not has_id:
            msg = (
                "set LATTICE_ENVIRONMENT_TOKEN, or both LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_adsbx(self) -> Self:
        """When ADS-B Exchange is the source, require its key and a quota-safe poll interval."""
        if self.adsb_source != "adsbx":
            return self
        if self.adsbx_rapidapi_key is None:
            msg = "ADSBX_RAPIDAPI_KEY is required when ADSB_SOURCE=adsbx"
            raise ValueError(msg)
        if self.adsbx_monthly_quota is None:
            msg = "ADSBX_MONTHLY_QUOTA is required when ADSB_SOURCE=adsbx"
            raise ValueError(msg)
        minimum = min_poll_seconds(self.adsbx_monthly_quota)
        if self.adsbx_poll_seconds < minimum:
            msg = (
                f"ADSBX_POLL_SECONDS must be at least {minimum:g} to stay under "
                f"ADSBX_MONTHLY_QUOTA={self.adsbx_monthly_quota}"
            )
            raise ValueError(msg)
        return self

    @property
    def aoi(self) -> BoundingBox:
        """The area of interest as a box."""
        return BoundingBox(
            south=self.aoi_south, west=self.aoi_west, north=self.aoi_north, east=self.aoi_east
        )

    def require_aisstream_api_key(self) -> SecretStr:
        """Return the AISStream key, or raise ``ConfigError`` naming the variable."""
        if self.aisstream_api_key is None:
            msg = "AISSTREAM_API_KEY: required for ais-ingest"
            raise ConfigError(msg)
        return self.aisstream_api_key

    def require_receiver_location(self) -> tuple[float, float]:
        """Return the antenna ``(lat, lon)``, or raise ``ConfigError`` naming the variables."""
        if self.receiver_lat is None or self.receiver_lon is None:
            msg = "RECEIVER_LAT and RECEIVER_LON: required for sdr-check"
            raise ConfigError(msg)
        return self.receiver_lat, self.receiver_lon


def min_poll_seconds(monthly_quota: int) -> float:
    """Return the shortest poll interval that keeps a month of calls within the quota."""
    return SECONDS_PER_30_DAYS / monthly_quota


def describe_errors(error: ValidationError) -> str:
    """Turn a pydantic validation error into lines that name environment variables.

    Input values are deliberately left out so a secret can never be echoed back.
    """
    lines: list[str] = []
    for item in error.errors(include_input=False, include_url=False, include_context=False):
        location = ".".join(str(part) for part in item["loc"]).upper()
        message = item["msg"].removeprefix("Value error, ")
        lines.append(f"{location}: {message}" if location else message)
    return "\n".join(lines)


def load_settings(env_file: str | None = ".env") -> Settings:
    """Load and validate settings.

    Args:
        env_file: Optional dotenv file read in addition to the process environment.
            Pass ``None`` to read the environment only.

    Raises:
        ConfigError: If a value is missing or invalid. The message names each variable.
    """
    try:
        return Settings(_env_file=env_file)
    except ValidationError as error:
        msg = f"Invalid configuration:\n{describe_errors(error)}"
        raise ConfigError(msg) from None
