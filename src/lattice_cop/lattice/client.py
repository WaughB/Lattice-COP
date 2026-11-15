# SPDX-License-Identifier: Apache-2.0
"""Lattice REST client setup, following Anduril's REST AIS sample app."""

from typing import Any

from anduril import AsyncLattice, Lattice

from lattice_cop.config import ConfigError, Settings

SANDBOX_HEADER = "Anduril-Sandbox-Authorization"
"""Header that carries the account-level Sandboxes token on every call."""

DEFAULT_TIMEOUT_SECONDS = 15.0


def _client_arguments(settings: Settings, max_retries: int | None) -> dict[str, Any]:
    """Return the constructor arguments shared by the sync and async clients.

    Authenticates with the environment token, or with the client ID and secret
    (the SDK then fetches and refreshes access tokens itself). The Sandboxes
    token goes in the ``Anduril-Sandbox-Authorization`` header.
    """
    sandbox_token = settings.lattice_sandboxes_token.get_secret_value()
    arguments: dict[str, Any] = {
        "base_url": f"https://{settings.lattice_url}",
        "headers": {SANDBOX_HEADER: f"Bearer {sandbox_token}"},
        "timeout": DEFAULT_TIMEOUT_SECONDS,
        "max_retries": max_retries,
    }
    if settings.lattice_environment_token is not None:
        arguments["token"] = settings.lattice_environment_token.get_secret_value()
        return arguments
    if settings.lattice_client_id is None or settings.lattice_client_secret is None:
        # Settings validation makes this unreachable; the check keeps the types honest.
        msg = "LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET: both are required"
        raise ConfigError(msg)
    arguments["client_id"] = settings.lattice_client_id
    arguments["client_secret"] = settings.lattice_client_secret.get_secret_value()
    return arguments


def build_client(settings: Settings, *, max_retries: int | None = None) -> Lattice:
    """Create a blocking Lattice client (used by the smoke test).

    Args:
        settings: Validated settings.
        max_retries: Overrides the SDK's own retry count.
    """
    return Lattice(**_client_arguments(settings, max_retries))


def build_async_client(settings: Settings, *, max_retries: int | None = 0) -> AsyncLattice:
    """Create the one async Lattice client an ingest service uses for its whole life.

    Args:
        settings: Validated settings.
        max_retries: The SDK's own retry count. It is 0 by default because the
            publisher does its own retries and must never retry a 4xx.
    """
    return AsyncLattice(**_client_arguments(settings, max_retries))
