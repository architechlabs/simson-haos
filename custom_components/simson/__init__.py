"""Simson: call between phones and extensions, with Home Assistant automations."""

from __future__ import annotations

import logging

from homeassistant.components.application_credentials import ClientCredential, async_import_client_credential
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SimsonApi
from .const import API_BASE, CLIENT_ID, DOMAIN
from .coordinator import SimsonConfigEntry, SimsonCoordinator, SimsonRuntime
from .frontend import async_register_card
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor", "event"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the public OAuth client, the services and the dashboard card once."""
    try:
        await async_import_client_credential(hass, DOMAIN, ClientCredential(CLIENT_ID, ""))
    except Exception:  # already imported on a previous start
        _LOGGER.debug("Simson OAuth client was already registered")
    await async_register_services(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry) -> bool:
    try:
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    except config_entry_oauth2_flow.ImplementationUnavailableError as error:
        raise ConfigEntryNotReady("The Simson sign-in service is not available yet.") from error
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    async def token() -> str:
        await session.async_ensure_token_valid()
        return session.token["access_token"]

    api = SimsonApi(async_get_clientsession(hass), API_BASE, token)
    coordinator = SimsonCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SimsonRuntime(coordinator=coordinator, api=api)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SimsonConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
