"""Download diagnostics with every secret and personal identifier removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import SimsonConfigEntry

REDACT = {"token", "access_token", "refresh_token", "id_token", "tenant_id", "site_id", "tenant_name", "site_name", "password", "username", "server"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SimsonConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data.coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "workspace": {
            "presence_state": data.presence_state,
            "phones": len([ext for ext in data.extensions.values() if not ext.gateway]),
            "phones_online": len([ext for ext in data.extensions.values() if ext.online]),
            "presets": len(data.automations),
            "numbers": len(data.numbers),
            "active_calls": data.active_calls,
            "calls_seen": data.total_calls,
        },
    }
