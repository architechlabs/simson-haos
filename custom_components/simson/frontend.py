"""Serve and auto-load the Simson dashboard card."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_VERSION = "0.1.1"
CARD_PATH = "/simson/www"
CARD_URL = f"{CARD_PATH}/simson-card.js?v={CARD_VERSION}"


async def async_register_card(hass: HomeAssistant) -> None:
    """Register the static files and load the tiny entry script on every page.

    The URL carries the version, so the files can be cached for a long time; a new
    release changes the URL and every browser picks it up on the next load.
    """
    state = hass.data.setdefault(f"{DOMAIN}_frontend", {})
    if state.get("registered"):
        return
    try:
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_PATH, str(Path(__file__).parent / "www"), cache_headers=True)])
        add_extra_js_url(hass, CARD_URL)
    except Exception as error:  # the integration must keep working without the card
        _LOGGER.warning("Could not register the Simson card: %s", error)
        return
    state["registered"] = True
