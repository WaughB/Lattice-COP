# SPDX-License-Identifier: Apache-2.0
"""Lattice REST client setup, following Anduril's REST AIS sample app."""

from anduril import Lattice

from lattice_cop.config import ConfigError, Settings

SANDBOX_HEADER = "Anduril-Sandbox-Authorization"
"""Header that carries the account-level Sandboxes token on every call."""

DEFAULT_TIMEOUT_SECONDS = 15.0


def build_client(settings: Settings, *, max_retries: int | None = None) -> Lattice:
    """Create the one Lattice client a service uses for its whole life.

    Authenticates with the environment token, or with the client ID and secret
    (the SDK then fetches and refreshes access tokens itself). The Sandboxes
    token goes in the ``Anduril-Sandbox-Authorization`` header.

    Args:
        settings: Validated settings.
        max_retries: Overrides the SDK's own retry count. Pass ``0`` when the
            caller does its own retries.
    """
    sandbox_token = settings.lattice_sandboxes_token.get_secret_value()
    base_url = f"https://{settings.lattice_url}"
    headers = {SANDBOX_HEADER: f"Bearer {sandbox_token}"}

    if settings.lattice_environment_token is not None:
        return Lattice(
            base_url=base_url,
            token=settings.lattice_environment_token.get_secret_value(),
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            max_retries=max_retries,
        )

    if settings.lattice_client_id is None or settings.lattice_client_secret is None:
        # Settings validation makes this unreachable; the check keeps the types honest.
        msg = "LATTICE_CLIENT_ID and LATTICE_CLIENT_SECRET: both are required"
        raise ConfigError(msg)
    return Lattice(
        base_url=base_url,
        client_id=settings.lattice_client_id,
        client_secret=settings.lattice_client_secret.get_secret_value(),
        headers=headers,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        max_retries=max_retries,
    )
