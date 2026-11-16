# SPDX-License-Identifier: Apache-2.0
"""Read aircraft.json from readsb (wiedehopf) over HTTP.

Field names follow readsb's README-json.md. Values are kept as readsb reports
them (feet, knots, degrees, feet per minute); cleaning and conversion come later.
Registration, type, operator and build year are only present when readsb runs
with its aircraft database (``TAR1090_ENABLE_AC_DB`` in the ultrafeeder image).
"""

from dataclasses import dataclass
from typing import Final

import httpx

NON_ICAO_PREFIX: Final = "~"
"""readsb marks addresses that are not ICAO-assigned (such as TIS-B) with this prefix."""

FETCH_TIMEOUT_SECONDS: Final = 3.0


class ReadsbError(Exception):
    """aircraft.json could not be fetched or did not have the expected shape."""


@dataclass(frozen=True, slots=True)
class Aircraft:
    """One entry of readsb's ``aircraft`` array, reduced to what is used."""

    hex: str
    latitude: float | None = None
    longitude: float | None = None
    seen_pos: float | None = None
    flight: str | None = None
    registration: str | None = None
    type_code: str | None = None
    alt_geom_ft: float | None = None
    alt_baro_ft: float | None = None
    on_ground: bool = False
    """readsb reports ``alt_baro`` as the string ``ground`` for aircraft on the ground."""
    ground_speed_kn: float | None = None
    track_deg: float | None = None
    true_heading_deg: float | None = None
    geom_rate_fpm: float | None = None
    baro_rate_fpm: float | None = None
    squawk: str | None = None
    category: str | None = None
    """ADS-B emitter category, ``A0`` to ``D7``."""
    emergency: str | None = None
    """ADS-B emergency or priority status, such as ``none`` or ``general``."""
    position_source: str | None = None
    """readsb's ``type``: how the best data arrived, such as ``adsb_icao`` or ``tisb_icao``."""
    selected_altitude_ft: float | None = None
    """The altitude set on the autopilot panel."""
    type_name: str | None = None
    """Long type name. This and the three fields below come from readsb's aircraft database."""
    operator: str | None = None
    year_built: str | None = None
    db_flags: int = 0
    """Database bit field: 1 military, 2 interesting, 4 PIA, 8 LADD."""

    @property
    def is_icao(self) -> bool:
        """Whether the address is a real ICAO address (not TIS-B or similar)."""
        return not self.hex.startswith(NON_ICAO_PREFIX)

    @property
    def position(self) -> tuple[float, float] | None:
        """``(latitude, longitude)`` if readsb has a position for the aircraft."""
        if self.latitude is None or self.longitude is None:
            return None
        return self.latitude, self.longitude


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One aircraft.json document."""

    now: float
    """When readsb wrote the file, in seconds since the Unix epoch."""
    messages: int
    """Mode S messages processed since readsb started. It drops when readsb restarts."""
    aircraft: tuple[Aircraft, ...]


def _number(value: object) -> float | None:
    """Return ``value`` as a float if it is a real number, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: object) -> str | None:
    """Return ``value`` if it is a string, else ``None``. Padding is left for cleaning."""
    return value if isinstance(value, str) else None


def parse_snapshot(payload: object) -> Snapshot:
    """Turn a decoded aircraft.json document into a ``Snapshot``.

    Entries without a usable ``hex`` are skipped.

    Raises:
        ReadsbError: If the document is not an object with ``now``, ``messages``
            and an ``aircraft`` list.
    """
    if not isinstance(payload, dict):
        msg = "aircraft.json is not a JSON object"
        raise ReadsbError(msg)
    now, messages, entries = (
        _number(payload.get("now")),
        _number(payload.get("messages")),
        payload.get("aircraft"),
    )
    if now is None or messages is None or not isinstance(entries, list):
        msg = "aircraft.json is missing now, messages or aircraft"
        raise ReadsbError(msg)

    aircraft = tuple(
        Aircraft(
            hex=entry["hex"].lower(),
            latitude=_number(entry.get("lat")),
            longitude=_number(entry.get("lon")),
            seen_pos=_number(entry.get("seen_pos")),
            flight=_text(entry.get("flight")),
            registration=_text(entry.get("r")),
            type_code=_text(entry.get("t")),
            alt_geom_ft=_number(entry.get("alt_geom")),
            alt_baro_ft=_number(entry.get("alt_baro")),
            on_ground=entry.get("alt_baro") == "ground",
            ground_speed_kn=_number(entry.get("gs")),
            track_deg=_number(entry.get("track")),
            true_heading_deg=_number(entry.get("true_heading")),
            geom_rate_fpm=_number(entry.get("geom_rate")),
            baro_rate_fpm=_number(entry.get("baro_rate")),
            squawk=_text(entry.get("squawk")),
            category=_text(entry.get("category")),
            emergency=_text(entry.get("emergency")),
            position_source=_text(entry.get("type")),
            selected_altitude_ft=_number(entry.get("nav_altitude_mcp")),
            type_name=_text(entry.get("desc")),
            operator=_text(entry.get("ownOp")),
            year_built=_text(entry.get("year")),
            db_flags=int(_number(entry.get("dbFlags")) or 0),
        )
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("hex"), str) and entry["hex"]
    )
    return Snapshot(now=now, messages=int(messages), aircraft=aircraft)


def _read(response: httpx.Response) -> Snapshot:
    """Turn an HTTP answer into a snapshot, or raise ``ReadsbError``."""
    if not response.is_success:
        msg = f"readsb answered HTTP {response.status_code}"
        raise ReadsbError(msg)
    try:
        payload = response.json()
    except ValueError:
        msg = "aircraft.json is not valid JSON"
        raise ReadsbError(msg) from None
    return parse_snapshot(payload)


def fetch_snapshot(client: httpx.Client, url: str) -> Snapshot:
    """Fetch and parse aircraft.json.

    Raises:
        ReadsbError: On any transport error, a non-2xx answer, or a bad document.
    """
    try:
        response = client.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        msg = f"could not reach readsb ({type(error).__name__})"
        raise ReadsbError(msg) from None
    return _read(response)


async def fetch_snapshot_async(client: httpx.AsyncClient, url: str) -> Snapshot:
    """Fetch and parse aircraft.json without blocking the event loop.

    Raises:
        ReadsbError: On any transport error, a non-2xx answer, or a bad document.
    """
    try:
        response = await client.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        msg = f"could not reach readsb ({type(error).__name__})"
        raise ReadsbError(msg) from None
    return _read(response)
