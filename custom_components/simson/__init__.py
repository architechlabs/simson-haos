"""Simson: call between phones and extensions, with Home Assistant automations."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.typing import ConfigType

from .api import SimsonApi
from .const import API_BASE
from .coordinator import SimsonConfigEntry, SimsonCoordinator, SimsonRuntime
from .frontend import async_register_card
from .oauth import SimsonOAuth2Implementation
from .services import async_register_services

PLATFORMS = ["binary_sensor", "sensor", "event", "button", "select"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and dashboard card once."""
    await async_register_services(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry) -> bool:
    session = OAuth2Session(hass, entry, SimsonOAuth2Implementation(hass))

    async def token() -> str:
        await session.async_ensure_token_valid()
        return session.token["access_token"]

    api = SimsonApi(async_get_clientsession(hass), API_BASE, token)
    coordinator = SimsonCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SimsonRuntime(coordinator=coordinator, api=api)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.streamer.start()
    entry.async_on_unload(coordinator.streamer.stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SimsonConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
