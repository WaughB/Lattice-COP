# SPDX-License-Identifier: Apache-2.0
"""Replay the synthetic message files and check the keep and drop counts.

The files in tests/fixtures are made up: no line was captured from a live feed.
The AIS file holds one arrival per line (``received_at`` plus the message); the
ADS-B file holds one aircraft.json document per line.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from lattice_cop.clean import adsb, ais
from lattice_cop.clean.throttle import Throttle
from lattice_cop.geo import BoundingBox
from lattice_cop.models import Track
from lattice_cop.sources.readsb import parse_snapshot

FIXTURES = Path(__file__).parent / "fixtures"
AOI = BoundingBox(south=27.40, west=-83.00, north=28.20, east=-82.25)


def lines(name: str) -> list[dict[str, Any]]:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def replay_ais(rules: ais.AisRules) -> tuple[Counter[str], list[Track], int]:
    """Run the AIS file through the cleaner and a 10 s throttle."""
    cleaner, throttle = ais.AisCleaner(rules), Throttle(10.0)
    published: list[Track] = []
    throttled = 0
    for entry in lines("ais_replay.jsonl"):
        now = datetime.fromisoformat(entry["received_at"])
        track = cleaner.clean(entry["message"], now)
        if track is None:
            continue
        fingerprint = (track.name, track.description, track.callsign)
        if throttle.allow(track.key, now.timestamp(), fingerprint):
            published.append(track)
        else:
            throttled += 1
    return cleaner.counts, published, throttled


def test_ais_replay_gives_the_expected_counts() -> None:
    # The fixture's MMSIs are in the synthetic 999 range, so the vessel rule is relaxed.
    counts, published, throttled = replay_ais(ais.AisRules(aoi=AOI, allow_non_vessel_mmsi=True))

    assert counts == {
        "kept": 6,
        "static_cached": 3,
        "invalid_position": 2,
        "duplicate": 1,
        "position_jump": 1,
        "outside_aoi": 1,
        "stale": 1,
        "invalid_static": 1,
        "unsupported": 1,
        "malformed": 1,
    }
    assert sum(counts.values()) == len(lines("ais_replay.jsonl")) == 18
    assert throttled == 1
    assert [(track.key, track.name) for track in published] == [
        ("999000001", "SYNTHETIC ONE"),
        ("999000001", "SYNTHETIC ONE"),
        ("999000005", "MMSI 999000005"),
        # Sent early, inside the 10 s window, because the name and details arrived.
        ("999000005", "SYNTHETIC FIVE"),
        ("999000001", "SYNTHETIC ONE"),
    ]
    assert published[0].description == (
        "Cargo; 190 m x 32 m; destination SYNTHETIC PORT; under way using engine; call sign SYN1"
    )
    assert published[2].speed_kn is None
    assert published[2].heading_deg is None
    assert published[3].description == "Pleasure craft; 12 m x 4 m; call sign SYN5"
    assert published[3].heading_deg == 10.0


def test_ais_replay_with_default_rules_drops_the_synthetic_mmsi_range() -> None:
    counts, published, throttled = replay_ais(ais.AisRules(aoi=AOI))

    assert counts == {
        "mmsi_not_vessel": 12,
        "invalid_position": 2,
        "outside_aoi": 1,
        "invalid_static": 1,
        "unsupported": 1,
        "malformed": 1,
    }
    assert published == []
    assert throttled == 0


def test_adsb_replay_gives_the_expected_counts() -> None:
    cleaner = adsb.AdsbCleaner(adsb.AdsbRules(aoi=AOI, center=(27.9755, -82.5332)))
    throttle = Throttle(2.0)
    published: list[Track] = []
    throttled = 0
    documents = lines("adsb_replay.jsonl")
    for document in documents:
        snapshot = parse_snapshot(document)
        for track in cleaner.clean_snapshot(snapshot):
            if throttle.allow(track.key, snapshot.now):
                published.append(track)
            else:
                throttled += 1

    assert cleaner.counts == {
        "kept": 7,
        "no_position": 1,
        "stale": 1,
        "outside_aoi": 1,
        "non_icao": 1,
        "position_jump": 1,
        "emergency_squawk": 1,
    }
    entries = sum(len(document["aircraft"]) for document in documents)
    assert entries == 12
    assert sum(cleaner.counts.values()) - cleaner.counts["emergency_squawk"] == entries
    assert throttled == 1
    assert [track.key for track in published] == [
        "ffff01",
        "ffff06",
        "ffff07",
        "ffff08",
        "ffff09",
        "ffff06",
    ]
    by_key = {track.key: track for track in published}
    assert by_key["ffff01"].name == "SYN101"
    assert published[0].description == (
        "SYNTHETIC JET 700 (SYN7); large aircraft; registration SYN-REG1; "
        "operator SYNTHETIC AIR; built 2015; squawk 6005; barometric altitude 34,800 ft"
    )
    assert published[0].specific_type == "SYNTHETIC JET 700"
    assert by_key["ffff07"].description == "on ground"
    assert by_key["ffff08"].name == "SYN-REG8"
    assert "EMERGENCY: general emergency" in by_key["ffff08"].description
    assert by_key["ffff09"].name == "ffff09"
    assert by_key["ffff08"].emergency is True
    assert published[1].description == "barometric altitude 3,000 ft; altitude approximate"
