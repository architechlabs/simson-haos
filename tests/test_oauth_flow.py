"""Exercise first-time Simson setup and callback in Home Assistant Core."""

import base64
import hashlib
from pathlib import Path
from shutil import copytree, ignore_patterns
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

async def test_add_simson_uses_the_builtin_oauth_client(tmp_path, monkeypatch):
    pytest.importorskip("homeassistant")
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    from homeassistant import loader
    from homeassistant.components.http import KEY_HASS
    from homeassistant.config_entries import ConfigEntries
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResultType
    from homeassistant.helpers.config_entry_oauth2_flow import OAuth2AuthorizeCallbackView

    from custom_components.simson import config_flow
    from custom_components.simson.api import SimsonApi
    from custom_components.simson.const import CLIENT_ID, DOMAIN, OAUTH_AUTHORIZE_URL, SCOPES
    from custom_components.simson.oauth import SimsonOAuth2Implementation

    source = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    copytree(source, tmp_path / "custom_components" / DOMAIN, ignore=ignore_patterns("__pycache__"))
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    integration = await loader.async_get_integration(hass, DOMAIN)
    assert "application_credentials" not in integration.dependencies
    await integration.async_get_platform("config_flow")

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth"
    url = urlsplit(result["url"])
    query = parse_qs(url.query)

    assert url._replace(query="").geturl() == OAUTH_AUTHORIZE_URL
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == ["https://my.home-assistant.io/redirect/oauth"]
    assert query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == set(SCOPES)
    assert 1 <= len(query["state"][0]) <= 512

    async def exchange(implementation, data):
        verifier = data["code_verifier"]
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert query["code_challenge"] == [challenge]
        assert implementation.client_id == CLIENT_ID
        assert not implementation.client_secret
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "fixture-authorization-code"
        assert data["redirect_uri"] == query["redirect_uri"][0]
        return {"access_token": "fixture-token", "expires_in": 3600}

    async def profile(api):
        return {"memberships": [{"tenant_id": "fixture-workspace", "role": "admin"}]}

    async def sites(api, tenant):
        assert tenant == "fixture-workspace"
        return [{"id": "first"}, {"id": "second"}]

    monkeypatch.setattr(SimsonOAuth2Implementation, "_token_request", exchange)
    monkeypatch.setattr(SimsonApi, "me", profile)
    monkeypatch.setattr(SimsonApi, "sites", sites)
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: None)
    app = web.Application()
    app[KEY_HASS] = hass
    callback = OAuth2AuthorizeCallbackView()
    request_query = urlencode({"state": query["state"][0], "code": "fixture-authorization-code"})
    response = await callback.get(make_mocked_request("GET", f"{callback.url}?{request_query}", app=app))
    assert response.status == 200
    continued = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert continued["type"] == FlowResultType.FORM
    assert continued["step_id"] == "site"
