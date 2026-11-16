# SPDX-License-Identifier: Apache-2.0
"""Reading the receiver's airline table. HTTP is mocked; every airline is made up."""

from typing import Any

import httpx
import pytest
import respx

from tampa_cop.sources import airlines

RECEIVER_URL = "http://readsb.invalid/data/aircraft.json"
ROOT = "http://readsb.invalid/"
TABLE_URL = "http://readsb.invalid/db-9.9.1/operators.js"
PAGE = '<html><script>\ndatabaseFolder = "db-9.9.1";\n</script></html>'
TABLE: dict[str, Any] = {
    "SYN": {"n": "Synthetic Air", "c": "Nowhere", "r": "SYNTH"},
    "FAK": {"n": "  Fake Freight  ", "c": "Nowhere", "r": ""},
}


def test_parse_keeps_three_letter_codes_with_a_name() -> None:
    table = {
        **TABLE,
        "TOOLONG": {"n": "Not a code"},
        "abc": {"n": "Lower case"},
        "NON": {"n": ""},
        "NUM": {"n": 7},
        "STR": "not an object",
        9: {"n": "Number key"},
    }
    assert airlines.parse_airlines(table) == {"SYN": "Synthetic Air", "FAK": "Fake Freight"}


@pytest.mark.parametrize("payload", [[], "text", None, {}, {"SYN": {"n": " "}}])
def test_parse_rejects_a_table_with_no_airline(payload: object) -> None:
    with pytest.raises(airlines.AirlineTableError):
        airlines.parse_airlines(payload)


@respx.mock
async def test_fetch_finds_the_database_folder_then_reads_the_table() -> None:
    page = respx.get(ROOT).mock(return_value=httpx.Response(200, text=PAGE))
    table = respx.get(TABLE_URL).mock(return_value=httpx.Response(200, json=TABLE))
    async with httpx.AsyncClient() as client:
        found = await airlines.fetch_airlines(client, RECEIVER_URL)
    assert found == {"SYN": "Synthetic Air", "FAK": "Fake Freight"}
    assert page.call_count == table.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    ("page", "table", "reason"),
    [
        (httpx.ConnectError("refused"), None, "could not reach the receiver for its start page"),
        (httpx.Response(503), None, "HTTP 503 for its start page"),
        (httpx.Response(200, text="<html></html>"), None, "does not name its database folder"),
        (httpx.Response(200, text=PAGE), httpx.Response(404), "HTTP 404 for its airline table"),
        (httpx.Response(200, text=PAGE), httpx.ReadTimeout("slow"), "(ReadTimeout)"),
        (httpx.Response(200, text=PAGE), httpx.Response(200, text="var x = 1;"), "not valid JSON"),
        (httpx.Response(200, text=PAGE), httpx.Response(200, json=[]), "not a JSON object"),
    ],
)
async def test_fetch_fails_with_a_reason(
    page: httpx.Response | Exception, table: httpx.Response | Exception | None, reason: str
) -> None:
    for url, answer in ((ROOT, page), (TABLE_URL, table)):
        if isinstance(answer, Exception):
            respx.get(url).mock(side_effect=answer)
        elif answer is not None:
            respx.get(url).mock(return_value=answer)
    async with httpx.AsyncClient() as client:
        with pytest.raises(
            airlines.AirlineTableError, match=reason.replace("(", r"\(").replace(")", r"\)")
        ):
            await airlines.fetch_airlines(client, RECEIVER_URL)
