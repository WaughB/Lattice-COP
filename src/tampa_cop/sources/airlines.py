# SPDX-License-Identifier: Apache-2.0
"""Airline names by ICAO code, read from the receiver's own tar1090 database.

The ultrafeeder image serves tar1090's ``operators.js``: a JSON object keyed by
the three-letter ICAO airline code, such as ``{"AAA": {"n": "Name", ...}}``.
tar1090 keeps it in a folder whose name carries the database version; the
folder is named on tar1090's start page. Nothing here leaves the stack.
"""

import re
from typing import Final

import httpx

DATABASE_FOLDER: Final = re.compile(r'databaseFolder\s*=\s*"(db-[0-9A-Za-z._-]+)"')
"""How tar1090's start page names the folder that holds its database files."""

OPERATORS_FILE: Final = "operators.js"
AIRLINE_CODE: Final = re.compile(r"[A-Z]{3}")
FETCH_TIMEOUT_SECONDS: Final = 5.0


class AirlineTableError(Exception):
    """The receiver's airline table could not be fetched or was not usable."""


def parse_airlines(payload: object) -> dict[str, str]:
    """Reduce a decoded ``operators.js`` document to ``{ICAO code: airline name}``.

    Entries without a three-letter code or a name are skipped.

    Raises:
        AirlineTableError: If the document is not an object or names no airline.
    """
    if not isinstance(payload, dict):
        msg = "the airline table is not a JSON object"
        raise AirlineTableError(msg)
    airlines: dict[str, str] = {}
    for code, entry in payload.items():
        name = entry.get("n") if isinstance(entry, dict) else None
        if isinstance(code, str) and AIRLINE_CODE.fullmatch(code) and isinstance(name, str):
            name = name.strip()
            if name:
                airlines[code] = name
    if not airlines:
        msg = "the airline table names no airline"
        raise AirlineTableError(msg)
    return airlines


async def _get(client: httpx.AsyncClient, url: httpx.URL, what: str) -> httpx.Response:
    """Fetch one document from the receiver, or raise ``AirlineTableError``."""
    try:
        response = await client.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        msg = f"could not reach the receiver for {what} ({type(error).__name__})"
        raise AirlineTableError(msg) from None
    if not response.is_success:
        msg = f"the receiver answered HTTP {response.status_code} for {what}"
        raise AirlineTableError(msg)
    return response


async def fetch_airlines(client: httpx.AsyncClient, receiver_url: str) -> dict[str, str]:
    """Fetch the airline table from the receiver that serves ``receiver_url``.

    Args:
        client: HTTP client.
        receiver_url: The aircraft.json address. Only its scheme and host are used.

    Returns:
        Airline names keyed by three-letter ICAO code.

    Raises:
        AirlineTableError: On any transport error, a non-2xx answer, a start
            page that does not name the database folder, or a bad table.
    """
    root = httpx.URL(receiver_url).join("/")
    page = await _get(client, root, "its start page")
    folder = DATABASE_FOLDER.search(page.text)
    if folder is None:
        msg = "the receiver's start page does not name its database folder"
        raise AirlineTableError(msg)
    table = await _get(client, root.join(f"{folder[1]}/{OPERATORS_FILE}"), "its airline table")
    try:
        payload = table.json()
    except ValueError:
        msg = "the airline table is not valid JSON"
        raise AirlineTableError(msg) from None
    return parse_airlines(payload)
