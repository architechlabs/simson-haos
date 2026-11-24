"""Check the authorization link against Home Assistant's actual PKCE helper."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

async def test_hacs_sign_in_sends_scopes_and_pkce_to_the_registered_callback(tmp_path):
    pytest.importorskip("homeassistant")
    from homeassistant.components.application_credentials import ClientCredential
    from homeassistant.core import HomeAssistant

    from custom_components.simson.application_credentials import async_get_auth_implementation
    from custom_components.simson.const import CLIENT_ID, DOMAIN, OAUTH_AUTHORIZE_URL, SCOPES

    hass = HomeAssistant(str(tmp_path))
    implementation = await async_get_auth_implementation(hass, DOMAIN, ClientCredential(CLIENT_ID, ""))
    url = urlsplit(await implementation.async_generate_authorize_url("simson-fixture-flow"))
    query = parse_qs(url.query)
    verifier = implementation.extra_token_resolve_data["code_verifier"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    assert url._replace(query="").geturl() == OAUTH_AUTHORIZE_URL
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == ["https://my.home-assistant.io/redirect/oauth"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [challenge]
    assert set(query["scope"][0].split()) == set(SCOPES)
    assert 1 <= len(query["state"][0]) <= 512
