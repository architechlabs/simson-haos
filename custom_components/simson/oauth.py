"""OAuth2 with PKCE against Simson. No client secret exists: the client is public."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce,
    MY_AUTH_CALLBACK_PATH,
)

from .const import CLIENT_ID, DOMAIN, OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL, SCOPES


class SimsonOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """The built-in public OAuth client registered by Simson."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass, DOMAIN, CLIENT_ID, OAUTH_AUTHORIZE_URL, OAUTH_TOKEN_URL, code_verifier_length=64)

    @property
    def redirect_uri(self) -> str:
        return MY_AUTH_CALLBACK_PATH

    @property
    def extra_authorize_data(self) -> dict:
        return {**super().extra_authorize_data, "scope": " ".join(SCOPES)}
