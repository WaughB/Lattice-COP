# SPDX-License-Identifier: Apache-2.0
"""Phase 1 smoke test: publish one synthetic vessel and let it expire.

The vessel is made up. MMSI 999000001 is not assigned to any real ship.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from anduril import (
    Aliases,
    AlternateId,
    Location,
    MilView,
    Ontology,
    Position,
    Provenance,
)

SMOKE_MMSI = 999000001
SMOKE_ENTITY_ID = f"lattice-cop-ais-{SMOKE_MMSI}"
SMOKE_NAME = "LATTICE-COP SMOKE TEST"
SMOKE_LAT = 27.7500
"""Open water in the middle of Tampa Bay, between St. Petersburg and Apollo Beach."""
SMOKE_LON = -82.5500
SMOKE_EXPIRY_SECONDS = 300.0


class EntityPublisher(Protocol):
    """The part of the Lattice entities client the smoke test needs."""

    def publish_entity(self, **kwargs: Any) -> Any:
        """Create or update one entity."""


def build_smoke_entity(
    now: datetime, expiry_seconds: float = SMOKE_EXPIRY_SECONDS
) -> dict[str, Any]:
    """Build the keyword arguments for ``publish_entity`` for the synthetic vessel.

    Args:
        now: Current time, timezone-aware. Expiry is counted from here.
        expiry_seconds: How long the vessel stays on the map.
    """
    return {
        "entity_id": SMOKE_ENTITY_ID,
        "description": "Synthetic vessel published by the Lattice-COP smoke test",
        "is_live": True,
        "created_time": now,
        "expiry_time": now + timedelta(seconds=expiry_seconds),
        "aliases": Aliases(
            name=SMOKE_NAME,
            alternate_ids=[AlternateId(id=str(SMOKE_MMSI), type="ALT_ID_TYPE_MMSI_ID")],
        ),
        "mil_view": MilView(disposition="DISPOSITION_NEUTRAL", environment="ENVIRONMENT_SURFACE"),
        "location": Location(
            position=Position(
                latitude_degrees=SMOKE_LAT,
                longitude_degrees=SMOKE_LON,
                altitude_hae_meters=0.0,
            )
        ),
        "ontology": Ontology(template="TEMPLATE_TRACK", platform_type="Surface Vessel"),
        "provenance": Provenance(
            integration_name="lattice-cop-ais",
            data_type="ais",
            source_update_time=now,
        ),
    }


def publish_smoke_entity(
    entities: EntityPublisher,
    *,
    now: datetime | None = None,
    expiry_seconds: float = SMOKE_EXPIRY_SECONDS,
) -> datetime:
    """Publish the synthetic vessel and return the time it will expire."""
    moment = now or datetime.now(UTC)
    entity = build_smoke_entity(moment, expiry_seconds)
    entities.publish_entity(**entity)
    expiry: datetime = entity["expiry_time"]
    return expiry
