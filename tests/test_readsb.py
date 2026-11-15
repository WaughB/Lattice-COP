# SPDX-License-Identifier: Apache-2.0
"""Reading readsb's aircraft.json. HTTP is mocked; every aircraft is synthetic."""

from typing import Any

import httpx
import pytest
import respx

from lattice_cop.sources import readsb

URL = "http://readsb.invalid/data/aircraft.json"


def document(
    *aircraft: dict[str, Any], now: float = 1_800_000_000.0, messages: int = 500
) -> dict[str, Any]:
    """Build a synthetic aircraft.json document."""
    return {"now": now, "messages": messages, "aircraft": list(aircraft)}


def test_parses_positions_and_ages() -> None:
    snapshot = readsb.parse_snapshot(
        document(
            {"hex": "FFFF01", "lat": 27.9, "lon": -82.5, "seen_pos": 0.4, "flight": "SYN001  "},
            {"hex": "ffff02", "seen": 3.1},
            {"hex": "~ffff03", "lat": 27.8, "lon": -82.6, "seen_pos": 2},
        )
    )

    assert snapshot.now == 1_800_000_000.0
    assert snapshot.messages == 500
    first, second, third = snapshot.aircraft
    assert first == readsb.Aircraft("ffff01", 27.9, -82.5, 0.4, flight="SYN001  ")
    assert first.position == (27.9, -82.5)
    assert first.is_icao is True
    assert second.position is None
    assert second.seen_pos is None
    assert third.is_icao is False
    assert third.seen_pos == 2.0


def test_skips_entries_without_a_usable_hex_or_with_bad_numbers() -> None:
    snapshot = readsb.parse_snapshot(
        document(
            {"lat": 27.9, "lon": -82.5},
            {"hex": ""},
            {"hex": 123},
            "not an object",
            {"hex": "ffff04", "lat": "27.9", "lon": True, "seen_pos": None},
        )
    )
    assert snapshot.aircraft == (readsb.Aircraft("ffff04"),)
    assert snapshot.aircraft[0].position is None


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "text",
        {},
        {"now": 1.0, "messages": 2},
        {"now": 1.0, "aircraft": []},
        {"messages": 2, "aircraft": []},
        {"now": True, "messages": 2, "aircraft": []},
        {"now": 1.0, "messages": 2, "aircraft": {}},
    ],
)
def test_rejects_documents_with_the_wrong_shape(payload: object) -> None:
    with pytest.raises(readsb.ReadsbError):
        readsb.parse_snapshot(payload)


@respx.mock
def test_fetches_and_parses() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=document({"hex": "ffff01"})))
    with httpx.Client() as client:
        snapshot = readsb.fetch_snapshot(client, URL)
    assert [aircraft.hex for aircraft in snapshot.aircraft] == ["ffff01"]


@respx.mock
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(503), "readsb answered HTTP 503"),
        (httpx.Response(200, text="<html>not json"), "aircraft.json is not valid JSON"),
        (httpx.Response(200, json=[1, 2]), "aircraft.json is not a JSON object"),
    ],
)
def test_bad_answers_become_readsb_errors(response: httpx.Response, message: str) -> None:
    respx.get(URL).mock(return_value=response)
    with httpx.Client() as client, pytest.raises(readsb.ReadsbError, match=message):
        readsb.fetch_snapshot(client, URL)


@respx.mock
@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_transport_errors_become_readsb_errors(error: Exception) -> None:
    respx.get(URL).mock(side_effect=error)
    with (
        httpx.Client() as client,
        pytest.raises(readsb.ReadsbError, match="could not reach readsb"),
    ):
        readsb.fetch_snapshot(client, URL)


def test_parses_the_fields_cleaning_needs() -> None:
    (aircraft,) = readsb.parse_snapshot(
        document(
            {
                "hex": "ffff01",
                "flight": "SYN001  ",
                "r": "SYN-REG1",
                "t": "B739",
                "alt_geom": 35250,
                "alt_baro": 35000,
                "gs": 462.1,
                "track": 91.5,
                "true_heading": 93.2,
                "geom_rate": -640,
                "baro_rate": -600,
                "squawk": "6005",
            }
        )
    ).aircraft

    assert aircraft == readsb.Aircraft(
        hex="ffff01",
        flight="SYN001  ",
        registration="SYN-REG1",
        type_code="B739",
        alt_geom_ft=35250.0,
        alt_baro_ft=35000.0,
        on_ground=False,
        ground_speed_kn=462.1,
        track_deg=91.5,
        true_heading_deg=93.2,
        geom_rate_fpm=-640.0,
        baro_rate_fpm=-600.0,
        squawk="6005",
    )


def test_alt_baro_ground_marks_the_aircraft_on_the_ground() -> None:
    (aircraft,) = readsb.parse_snapshot(
        document({"hex": "ffff01", "alt_baro": "ground", "squawk": 1200, "flight": 7})
    ).aircraft
    assert aircraft.on_ground is True
    assert aircraft.alt_baro_ft is None
    assert aircraft.squawk is None
    assert aircraft.flight is None
