"""OAuth2 with PKCE against Simson. No client secret exists: the client is public."""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer, ClientCredential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2Implementation, LocalOAuth2ImplementationWithPkce

from .const import OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL, SCOPES


class SimsonOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """Asks for the scopes the integration needs on the consent screen."""

    @property
    def extra_authorize_data(self) -> dict:
        return {"scope": " ".join(SCOPES)}


async def async_get_auth_implementation(hass: HomeAssistant, auth_domain: str, credential: ClientCredential) -> AbstractOAuth2Implementation:
    return SimsonOAuth2Implementation(
        hass,
        auth_domain,
        credential.client_id,
        authorize_url=OAUTH_AUTHORIZE_URL,
        token_url=OAUTH_TOKEN_URL,
        client_secret="",
        code_verifier_length=64,
    )


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    return AuthorizationServer(authorize_url=OAUTH_AUTHORIZE_URL, token_url=OAUTH_TOKEN_URL)
