# SPDX-License-Identifier: Apache-2.0
"""Builders for synthetic AIS messages and aircraft. Nothing here is real traffic."""

from datetime import UTC, datetime, timedelta
from typing import Any

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
"""Reference time for synthetic messages."""

IN_AOI = (27.75, -82.55)


def after(seconds: float) -> datetime:
    """Return ``T0`` plus a number of seconds."""
    return T0 + timedelta(seconds=seconds)


def time_utc(at: datetime) -> str:
    """Format a time the way AISStream does: nanoseconds and a zone name."""
    return at.strftime("%Y-%m-%d %H:%M:%S.%f") + "000 +0000 UTC"


def ais_position(  # noqa: PLR0913 - one argument per field a test may vary
    mmsi: int = 999000001,
    point: tuple[float, float] = IN_AOI,
    at: datetime = T0,
    *,
    kind: str = "PositionReport",
    sog: float = 8.2,
    cog: float = 91.0,
    heading: int = 90,
    valid: bool = True,
    nav_status: int | None = 0,
    ship_name: str = "",
) -> dict[str, Any]:
    """Build a synthetic position message in AISStream's envelope."""
    body: dict[str, Any] = {
        "UserID": mmsi,
        "Valid": valid,
        "Latitude": point[0],
        "Longitude": point[1],
        "Sog": sog,
        "Cog": cog,
        "TrueHeading": heading,
    }
    if nav_status is not None and kind == "PositionReport":
        body["NavigationalStatus"] = nav_status
    return {
        "MessageType": kind,
        "MetaData": {
            "MMSI": mmsi,
            "MMSI_String": mmsi,
            "ShipName": ship_name,
            "latitude": point[0],
            "longitude": point[1],
            "time_utc": time_utc(at),
        },
        "Message": {kind: body},
    }


def ais_ship_static(  # noqa: PLR0913 - one argument per field a test may vary
    mmsi: int = 999000001,
    *,
    name: str = "SYNTHETIC ONE@@@@@@@",
    callsign: str = "SYN1@@@",
    ship_type: int = 70,
    dimension: tuple[int, int, int, int] = (150, 40, 20, 12),
    destination: str = "SYNTHETIC PORT@@@@@@",
    valid: bool = True,
    at: datetime = T0,
) -> dict[str, Any]:
    """Build a synthetic class A static message (ShipStaticData)."""
    a, b, c, d = dimension
    return {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": mmsi, "MMSI_String": mmsi, "ShipName": name, "time_utc": time_utc(at)},
        "Message": {
            "ShipStaticData": {
                "UserID": mmsi,
                "Valid": valid,
                "Name": name,
                "CallSign": callsign,
                "Type": ship_type,
                "Dimension": {"A": a, "B": b, "C": c, "D": d},
                "Destination": destination,
            }
        },
    }


def ais_static_report(  # noqa: PLR0913 - one argument per field a test may vary
    mmsi: int = 999000005,
    *,
    name: str | None = None,
    callsign: str | None = None,
    ship_type: int = 37,
    dimension: tuple[int, int, int, int] = (8, 4, 2, 2),
    at: datetime = T0,
) -> dict[str, Any]:
    """Build a synthetic class B static message: part A if ``name`` is given, else part B."""
    part_a = name is not None
    a, b, c, d = dimension
    return {
        "MessageType": "StaticDataReport",
        "MetaData": {"MMSI": mmsi, "MMSI_String": mmsi, "ShipName": "", "time_utc": time_utc(at)},
        "Message": {
            "StaticDataReport": {
                "UserID": mmsi,
                "Valid": True,
                "PartNumber": not part_a,
                "ReportA": {"Valid": part_a, "Name": name or ""},
                "ReportB": {
                    "Valid": not part_a,
                    "CallSign": callsign or "",
                    "ShipType": ship_type if not part_a else 0,
                    "Dimension": (
                        {"A": a, "B": b, "C": c, "D": d}
                        if not part_a
                        else {"A": 0, "B": 0, "C": 0, "D": 0}
                    ),
                },
            }
        },
    }


def aircraft_entry(
    hex_code: str = "ffff01",
    point: tuple[float, float] | None = IN_AOI,
    seen_pos: float | None = 0.5,
    **fields: Any,
) -> dict[str, Any]:
    """Build one synthetic entry of readsb's ``aircraft`` array."""
    entry: dict[str, Any] = {"hex": hex_code}
    if point is not None:
        entry["lat"], entry["lon"] = point
    if seen_pos is not None:
        entry["seen_pos"] = seen_pos
    entry.update(fields)
    return entry
