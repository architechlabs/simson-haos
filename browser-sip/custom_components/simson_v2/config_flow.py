"""Authorize Home Assistant with Simson and select a location."""
import logging

import voluptuous as vol
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2FlowHandler

from .cloud import CloudUnavailable, Reauthorize, SimsonOAuth, api_path, cloud_get, protect_refresh, storage_cipher
from .protocol import API, DOMAIN, uuid_text


class SimsonConfigFlow(AbstractOAuth2FlowHandler, domain=DOMAIN):
    DOMAIN = DOMAIN
    VERSION = 1
    logger = logging.getLogger(__name__)

    async def async_step_user(self, user_input=None):
        try:
            self.cipher = await self.hass.async_add_executor_job(storage_cipher)
        except (OSError, ValueError):
            return self.async_abort(reason="missing_storage_key")
        self.flow_impl = SimsonOAuth(self.hass)
        return await self.async_step_auth()

    async def async_step_reauth(self, entry_data):
        return await self.async_step_user()

    async def async_step_creation(self, user_input=None):
        try:
            return await super().async_step_creation(user_input)
        except Reauthorize:
            return self.async_abort(reason="oauth_unauthorized")
        except CloudUnavailable:
            return self.async_abort(reason="oauth_failed")

    async def async_oauth_create_entry(self, data):
        self.token = data["token"]
        try:
            profile = await cloud_get(self.hass, f"{API}/integration/v1/me", self.token["access_token"])
            self.workspaces = {
                uuid_text(item["tenant_id"]): item.get("tenant_name") or item["tenant_id"]
                for item in profile.get("memberships", []) if item.get("role") == "admin"
            }
        except (KeyError, TypeError, ValueError, Reauthorize, CloudUnavailable):
            return self.async_abort(reason="no_workspaces")
        if not self.workspaces:
            return self.async_abort(reason="no_workspaces")
        if self.source == "reauth":
            entry = self._get_reauth_entry()
            if entry.data["tenant_id"] not in self.workspaces:
                return self.async_abort(reason="no_workspaces")
            try:
                await cloud_get(self.hass, f"{api_path(entry.data['tenant_id'], entry.data['site_id'])}/snapshot", self.token["access_token"])
            except (Reauthorize, CloudUnavailable):
                return self.async_abort(reason="no_sites")
            return self.async_update_reload_and_abort(entry, data_updates=self.encrypted_token(entry.data["tenant_id"], entry.data["site_id"]))
        if len(self.workspaces) == 1:
            return await self.async_step_workspace({"tenant_id": next(iter(self.workspaces))})
        return await self.async_step_workspace()

    def encrypted_token(self, tenant, site):
        return {"oauth_ciphertext": protect_refresh(self.cipher, tenant, site, self.token["refresh_token"])}

    async def async_step_workspace(self, user_input=None):
        if user_input is not None:
            self.tenant_id = user_input["tenant_id"]
            if self.tenant_id not in self.workspaces:
                return self.async_abort(reason="no_workspaces")
            try:
                self.sites = await self.list_sites()
            except (KeyError, TypeError, ValueError, Reauthorize, CloudUnavailable):
                return self.async_abort(reason="no_sites")
            if not self.sites:
                return self.async_abort(reason="no_sites")
            return await self.async_step_site()
        return self.async_show_form(step_id="workspace", data_schema=vol.Schema({vol.Required("tenant_id"): vol.In(self.workspaces)}))

    async def list_sites(self):
        sites = {}
        cursors = set()
        after = ""
        for _ in range(10):
            url = f"{api_path(self.tenant_id)}/sites?limit=100{after}"
            page = await cloud_get(self.hass, url, self.token["access_token"])
            sites.update((uuid_text(item["id"]), item["display_name"]) for item in page["items"])
            if not page.get("next_after"):
                return sites
            cursor = uuid_text(page["next_after"])
            if cursor in cursors:
                raise ValueError("Repeated site list cursor")
            cursors.add(cursor)
            after = f"&after={cursor}"
        return sites

    async def async_step_site(self, user_input=None):
        if user_input is not None:
            site_id = user_input["site_id"]
            if site_id not in self.sites:
                return self.async_abort(reason="no_sites")
            await self.async_set_unique_id(site_id)
            self._abort_if_unique_id_configured()
            result = self.async_create_entry(title=self.sites[site_id], data={
                "site_id": site_id, "tenant_id": self.tenant_id, **self.encrypted_token(self.tenant_id, site_id),
            })
            self.token = None
            return result
        return self.async_show_form(step_id="site", data_schema=vol.Schema({vol.Required("site_id"): vol.In(self.sites)}))
