"""Sign in with Simson, then pick a workspace and a location."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .api import SimsonApi, SimsonError
from .const import (
    API_BASE, CONF_BROWSER_EXTENSION, CONF_DEFAULT_EXTENSION, CONF_SCAN_ACTIVE, CONF_SCAN_IDLE,
    CONF_SITE_ID, CONF_SITE_NAME, CONF_TENANT_ID, CONF_TENANT_NAME, DEFAULT_BROWSER_EXTENSION, DOMAIN,
)
from .oauth import SimsonOAuth2Implementation

_LOGGER = logging.getLogger(__name__)


def _select(options: list[tuple[str, str]]) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=[SelectOptionDict(value=value, label=label) for value, label in options], mode=SelectSelectorMode.LIST))


class SimsonOptionsFlow(OptionsFlow):
    """Default calling phone and polling speed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            cleaned = {key: value for key, value in user_input.items() if value not in (None, "")}
            return self.async_create_entry(data=cleaned)
        current = self.config_entry.options
        schema = vol.Schema({
            vol.Required(CONF_BROWSER_EXTENSION, default=current.get(CONF_BROWSER_EXTENSION, DEFAULT_BROWSER_EXTENSION)):
                vol.All(str, vol.Match(r"^[1-9][0-9]{1,7}$")),
            vol.Optional(CONF_DEFAULT_EXTENSION, description={"suggested_value": current.get(CONF_DEFAULT_EXTENSION)}): str,
            vol.Optional(CONF_SCAN_IDLE, default=current.get(CONF_SCAN_IDLE, 30)): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
            vol.Optional(CONF_SCAN_ACTIVE, default=current.get(CONF_SCAN_ACTIVE, 4)): vol.All(vol.Coerce(int), vol.Range(min=2, max=60)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)


class SimsonFlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """OAuth2 + PKCE sign-in followed by workspace and location selection."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._oauth_data: dict[str, Any] = {}
        self._workspaces: dict[str, str] = {}
        self._tenant_id: str | None = None
        self._api: SimsonApi | None = None

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self.flow_impl = SimsonOAuth2Implementation(self.hass)
        return await self.async_step_auth()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SimsonOptionsFlow:
        return SimsonOptionsFlow()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        self._oauth_data = data
        token = data["token"]["access_token"]

        async def provider() -> str:
            return token

        self._api = SimsonApi(async_get_clientsession(self.hass), API_BASE, provider)
        try:
            profile = await self._api.me()
        except SimsonError:
            return self.async_abort(reason="cannot_connect")
        memberships = [m for m in profile.get("memberships", []) if m.get("role") == "admin"] or profile.get("memberships", [])
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            if not any(m.get("tenant_id") == entry.data.get(CONF_TENANT_ID) for m in memberships):
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data_updates=data)
        if not memberships:
            return self.async_abort(reason="no_workspace")
        self._workspaces = {m["tenant_id"]: m.get("tenant_name") or m["tenant_id"] for m in memberships}
        if len(self._workspaces) == 1:
            self._tenant_id = next(iter(self._workspaces))
            return await self.async_step_site()
        return await self.async_step_workspace()

    async def async_step_workspace(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._tenant_id = user_input[CONF_TENANT_ID]
            return await self.async_step_site()
        schema = vol.Schema({vol.Required(CONF_TENANT_ID): _select(list(self._workspaces.items()))})
        return self.async_show_form(step_id="workspace", data_schema=schema)

    async def async_step_site(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._api is not None and self._tenant_id is not None
        try:
            sites = await self._api.sites(self._tenant_id)
        except SimsonError:
            return self.async_abort(reason="cannot_connect")
        names = {site["id"]: site.get("display_name") or site["id"] for site in sites}
        if not names:
            return self.async_abort(reason="no_site")
        if user_input is None and len(names) > 1:
            return self.async_show_form(step_id="site", data_schema=vol.Schema({vol.Required(CONF_SITE_ID): _select(list(names.items()))}))
        site_id = user_input[CONF_SITE_ID] if user_input else next(iter(names))
        await self.async_set_unique_id(f"{self._tenant_id}:{site_id}")
        self._abort_if_unique_id_configured()
        workspace = self._workspaces.get(self._tenant_id, self._tenant_id)
        data = {**self._oauth_data, CONF_TENANT_ID: self._tenant_id, CONF_SITE_ID: site_id, CONF_TENANT_NAME: workspace, CONF_SITE_NAME: names[site_id]}
        return self.async_create_entry(title=f"{workspace} · {names[site_id]}", data=data)
