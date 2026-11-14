# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures. Every credential here is fake and exists only in tests."""

import os

import pytest

from lattice_cop.config import Settings

FAKE_HOST = "lattice-test.invalid"
FAKE_SANDBOX_TOKEN = "fake-sandbox-token"  # noqa: S105 - test value, not a credential
FAKE_ENV_TOKEN = "fake-environment-token"  # noqa: S105 - test value, not a credential
FAKE_CLIENT_SECRET = "fake-client-secret"  # noqa: S105 - test value, not a credential


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every Lattice-COP variable so the host's environment never leaks into a test."""
    names = {name.upper() for name in Settings.model_fields}
    for key in list(os.environ):
        if key.upper() in names:
            monkeypatch.delenv(key)


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal valid environment using an environment token."""
    monkeypatch.setenv("LATTICE_URL", FAKE_HOST)
    monkeypatch.setenv("LATTICE_SANDBOXES_TOKEN", FAKE_SANDBOX_TOKEN)
    monkeypatch.setenv("LATTICE_ENVIRONMENT_TOKEN", FAKE_ENV_TOKEN)


@pytest.fixture
def client_credentials_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal valid environment using a client ID and secret."""
    monkeypatch.setenv("LATTICE_URL", FAKE_HOST)
    monkeypatch.setenv("LATTICE_SANDBOXES_TOKEN", FAKE_SANDBOX_TOKEN)
    monkeypatch.setenv("LATTICE_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("LATTICE_CLIENT_SECRET", FAKE_CLIENT_SECRET)
