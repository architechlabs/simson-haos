"""Expose the Simson V2 calling integration and its local card assets."""

import logging
import asyncio
from pathlib import Path

from aiohttp import ClientError
from homeassistant.components.http import StaticPathConfig
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.storage import Store

from .automation import register_automation
from .cloud import CallFeed, Reauthorize, revoke, storage_cipher
from .inventory import InventoryFeed
from .protocol import DOMAIN
from .runtime import Site
from .transport import register

CARD_PATH = "/simson-v2"
LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor", "event", "button", "switch"]


def entry_store(hass, entry):
    return Store(hass, 1, f"{DOMAIN}.event_checkpoint.{entry.entry_id}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the dashboard module for this Home Assistant installation."""
    directory = Path(__file__).parent / "www"
    asset = directory / "simson-call-card.js"
    if not await hass.async_add_executor_job(asset.is_file):
        LOGGER.error("The Simson V2 call card bundle is missing. Install the complete release")
        return False
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_PATH, str(directory), cache_headers=False)]
    )
    hass.data[DOMAIN] = {"sites": {}}
    register(hass)
    register_automation(hass)
    return True


async def async_setup_entry(hass, entry):
    try:
        cipher = await hass.async_add_executor_job(storage_cipher)
    except (OSError, ValueError):
        raise ConfigEntryNotReady("Private Simson encryption key is unavailable") from None
    store = entry_store(hass, entry)
    try:
        checkpoint = await store.async_load()
    except (OSError, ValueError):
        raise ConfigEntryNotReady("Simson event checkpoint is unavailable") from None
    site = Site(hass, entry, store, checkpoint)
    entry.runtime_data = site
    hass.data[DOMAIN]["sites"][site.site_id] = site
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN]["sites"].pop(site.site_id, None)
        raise
    stream = CallFeed(site, cipher)
    site.inventory_feed = InventoryFeed(site, stream)
    site.tasks = [
        entry.async_create_background_task(hass, stream.run(), "Simson call events"),
        entry.async_create_background_task(hass, site.inventory_feed.run(), "Simson location presence"),
    ]
    site.schedule_expiry()
    return True


async def async_unload_entry(hass, entry):
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    site = entry.runtime_data
    hass.data[DOMAIN]["sites"].pop(site.site_id, None)
    site.stop_expiry()
    tasks = [*site.tasks, *site.notification_tasks]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        await site.flush()
    except OSError:
        LOGGER.warning("Simson could not save the location event checkpoint")
    return True


async def async_remove_entry(hass, entry):
    try:
        await entry_store(hass, entry).async_remove()
    except OSError:
        LOGGER.warning("Simson could not remove the location event checkpoint")
    try:
        if await revoke(hass, entry):
            return
    except (ClientError, OSError, TimeoutError, ValueError, Reauthorize):
        pass
    LOGGER.warning("Remove the Home Assistant grant in Simson connected apps if it is still listed")
