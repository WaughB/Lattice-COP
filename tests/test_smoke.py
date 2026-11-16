# SPDX-License-Identifier: Apache-2.0
"""The Phase 1 smoke-test entity: synthetic, in Tampa Bay, with a five-minute expiry."""

from datetime import UTC, datetime, timedelta
from typing import Any

from tampa_cop import smoke

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)


class FakeEntities:
    """Records publish calls instead of sending them."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    def publish_entity(self, **kwargs: Any) -> None:
        self.published.append(kwargs)


def test_smoke_entity_is_a_synthetic_surface_track_in_tampa_bay() -> None:
    entity = smoke.build_smoke_entity(NOW)

    assert entity["entity_id"] == "tampa-cop-ais-999000001"
    assert entity["is_live"] is True
    assert entity["aliases"].name == smoke.SMOKE_NAME
    alternate = entity["aliases"].alternate_ids[0]
    assert (alternate.id, alternate.type) == ("999000001", "ALT_ID_TYPE_MMSI_ID")
    assert entity["ontology"].template == "TEMPLATE_TRACK"
    assert entity["ontology"].platform_type == "Surface Vessel"
    assert entity["mil_view"].environment == "ENVIRONMENT_SURFACE"
    assert entity["mil_view"].disposition == "DISPOSITION_NEUTRAL"
    assert entity["provenance"].integration_name == "tampa-cop-ais"
    assert entity["provenance"].data_type == "ais"
    assert entity["provenance"].source_update_time == NOW

    position = entity["location"].position
    assert 27.40 <= position.latitude_degrees <= 28.20
    assert -83.00 <= position.longitude_degrees <= -82.25
    assert position.altitude_hae_meters == 0.0


def test_expiry_is_five_minutes_after_publish_by_default() -> None:
    entity = smoke.build_smoke_entity(NOW)
    assert entity["created_time"] == NOW
    assert entity["expiry_time"] == NOW + timedelta(minutes=5)


def test_publish_sends_one_entity_and_returns_its_expiry() -> None:
    entities = FakeEntities()
    expiry = smoke.publish_smoke_entity(entities, now=NOW, expiry_seconds=30)

    assert len(entities.published) == 1
    assert entities.published[0]["entity_id"] == smoke.SMOKE_ENTITY_ID
    assert expiry == NOW + timedelta(seconds=30)


def test_publish_uses_the_current_time_when_none_is_given() -> None:
    entities = FakeEntities()
    before = datetime.now(UTC)
    expiry = smoke.publish_smoke_entity(entities)
    after = datetime.now(UTC)

    assert before + timedelta(minutes=5) <= expiry <= after + timedelta(minutes=5)
