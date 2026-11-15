# SPDX-License-Identifier: Apache-2.0
"""Read aircraft.json from readsb (wiedehopf) over HTTP.

Field names follow readsb's README-json.md. Only the fields the signal gate
needs are read here; the ADS-B pipeline adds the rest in later phases.
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
        )
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("hex"), str) and entry["hex"]
    )
    return Snapshot(now=now, messages=int(messages), aircraft=aircraft)


def fetch_snapshot(client: httpx.Client, url: str) -> Snapshot:
    """Fetch and parse aircraft.json.

    Raises:
        ReadsbError: On any transport error, a non-2xx answer, or a bad document.
    """
    try:
        response = client.get(url, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as error:
        msg = f"readsb answered HTTP {error.response.status_code}"
        raise ReadsbError(msg) from None
    except httpx.HTTPError as error:
        msg = f"could not reach readsb ({type(error).__name__})"
        raise ReadsbError(msg) from None
    except ValueError:
        msg = "aircraft.json is not valid JSON"
        raise ReadsbError(msg) from None
    return parse_snapshot(payload)
