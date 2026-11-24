"""Serve and auto-load the Simson dashboard card."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_VERSION = "0.1.5"
CARD_PATH = "/simson/www"
RELEASE_PATH = f"{CARD_PATH}/v{CARD_VERSION}"
CARD_URL = f"{RELEASE_PATH}/simson-card.js"


async def async_register_card(hass: HomeAssistant) -> None:
    """Register the static files and load the tiny entry script on every page.

    The URL carries the version, so the files can be cached for a long time; a new
    release changes the URL and every browser picks it up on the next load.
    """
    state = hass.data.setdefault(f"{DOMAIN}_frontend", {})
    if state.get("registered"):
        return
    try:
        assets = str(Path(__file__).parent / "www")
        await hass.http.async_register_static_paths([
            StaticPathConfig(RELEASE_PATH, assets, cache_headers=True),
            StaticPathConfig(CARD_PATH, assets, cache_headers=False),
        ])
        add_extra_js_url(hass, CARD_URL)
    except Exception as error:  # the integration must keep working without the card
        _LOGGER.warning("Could not register the Simson card: %s", error)
        return
    state["registered"] = True
