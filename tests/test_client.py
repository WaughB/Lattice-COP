# SPDX-License-Identifier: Apache-2.0
"""Lattice client setup: base URL, sandbox header, and both ways to authenticate.

HTTP is mocked with respx. Nothing here reaches the network.
"""

import httpx
import pytest
import respx

from lattice_cop.config import ConfigError, Settings, load_settings
from lattice_cop.lattice.client import SANDBOX_HEADER, build_client
from tests.conftest import FAKE_CLIENT_SECRET, FAKE_ENV_TOKEN, FAKE_HOST, FAKE_SANDBOX_TOKEN

ENTITIES_URL = f"https://{FAKE_HOST}/api/v1/entities"
TOKEN_URL = f"https://{FAKE_HOST}/api/v1/oauth/token"


@pytest.mark.usefixtures("token_env")
@respx.mock
def test_environment_token_is_sent_with_the_sandbox_header() -> None:
    publish = respx.put(ENTITIES_URL).mock(
        return_value=httpx.Response(200, json={"entityId": "lattice-cop-ais-999000001"})
    )
    client = build_client(load_settings(env_file=None))

    entity = client.entities.publish_entity(entity_id="lattice-cop-ais-999000001")

    assert entity.entity_id == "lattice-cop-ais-999000001"
    request = publish.calls.last.request
    assert request.headers["authorization"] == f"Bearer {FAKE_ENV_TOKEN}"
    assert request.headers[SANDBOX_HEADER] == f"Bearer {FAKE_SANDBOX_TOKEN}"


@pytest.mark.usefixtures("client_credentials_env")
@respx.mock
def test_client_credentials_are_exchanged_for_an_access_token() -> None:
    token = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "issued", "expires_in": 3600, "token_type": "bearer"}
        )
    )
    publish = respx.put(ENTITIES_URL).mock(
        return_value=httpx.Response(200, json={"entityId": "lattice-cop-ais-999000001"})
    )
    client = build_client(load_settings(env_file=None))

    client.entities.publish_entity(entity_id="lattice-cop-ais-999000001")

    assert token.call_count == 1
    assert FAKE_CLIENT_SECRET in token.calls.last.request.content.decode()
    assert token.calls.last.request.headers[SANDBOX_HEADER] == f"Bearer {FAKE_SANDBOX_TOKEN}"
    assert publish.calls.last.request.headers["authorization"] == "Bearer issued"


@pytest.mark.usefixtures("token_env")
@respx.mock
def test_max_retries_zero_turns_off_sdk_retries() -> None:
    publish = respx.put(ENTITIES_URL).mock(return_value=httpx.Response(503, json={}))
    client = build_client(load_settings(env_file=None), max_retries=0)

    with pytest.raises(Exception, match="503"):
        client.entities.publish_entity(entity_id="lattice-cop-ais-999000001")

    assert publish.call_count == 1


def test_missing_credentials_raise_a_config_error() -> None:
    """Validation normally prevents this; the client still refuses to guess."""
    settings = Settings.model_construct(
        lattice_url=FAKE_HOST,
        lattice_sandboxes_token=load_fake_secret(),
        lattice_environment_token=None,
        lattice_client_id=None,
        lattice_client_secret=None,
    )
    with pytest.raises(ConfigError, match="LATTICE_CLIENT_ID"):
        build_client(settings)


def load_fake_secret() -> object:
    from pydantic import SecretStr  # noqa: PLC0415

    return SecretStr(FAKE_SANDBOX_TOKEN)
