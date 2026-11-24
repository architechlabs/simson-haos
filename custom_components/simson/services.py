"""simson.* services: call controls and read-only inventory for automations."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import SimsonConflict, SimsonError, SimsonNotFound, SimsonPermissionError, SimsonPlanError
from .const import (
    DOMAIN,
    SERVICE_CALL,
    SERVICE_CALL_EXTENSION,
    SERVICE_GET_EXTENSIONS,
    SERVICE_GET_HISTORY,
    SERVICE_GET_NUMBERS,
    SERVICE_GET_PRESETS,
    SERVICE_HANGUP,
    SERVICE_RUN_PRESET,
)
from .coordinator import SimsonConfigEntry
from .model import history_rows
from .resolve import ResolveError, default_caller, find_automation, plan_call, runnable


_TARGET = {vol.Optional("config_entry_id"): cv.string}
CALL_SCHEMA = vol.Schema({**_TARGET, vol.Required("from_extension"): cv.string, vol.Required("to_extension"): cv.string, vol.Optional("video", default=False): cv.boolean, vol.Optional("timeout", default=30): vol.All(vol.Coerce(int), vol.Range(min=10, max=120))})
HANGUP_SCHEMA = vol.Schema({**_TARGET, vol.Required("call_id"): cv.string})
CALL_EXTENSION_SCHEMA = vol.Schema({**_TARGET, vol.Required("to_extension"): cv.string, vol.Optional("from_extension"): cv.string, vol.Optional("video", default=False): cv.boolean, vol.Optional("timeout", default=30): vol.All(vol.Coerce(int), vol.Range(min=10, max=120))})
HISTORY_SCHEMA = vol.Schema({**_TARGET, vol.Optional("limit", default=25): vol.All(vol.Coerce(int), vol.Range(min=1, max=200))})
LIST_SCHEMA = vol.Schema({**_TARGET})


def _entry(hass: HomeAssistant, data: dict[str, Any]) -> SimsonConfigEntry:
    entries = [entry for entry in hass.config_entries.async_entries(DOMAIN) if getattr(entry, "runtime_data", None)]
    wanted = data.get("config_entry_id")
    if wanted:
        entries = [entry for entry in entries if entry.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("Simson is not set up in Home Assistant.")
    if len(entries) > 1:
        raise ServiceValidationError("More than one Simson location is configured. Choose one with config_entry_id.")
    return entries[0]


def _explain(error: Exception) -> HomeAssistantError:
    if isinstance(error, ResolveError):
        return ServiceValidationError(str(error))
    if isinstance(error, SimsonPlanError):
        return ServiceValidationError("This feature is not included in the workspace plan.")
    if isinstance(error, SimsonPermissionError):
        return ServiceValidationError("This Simson account is not allowed to do that. Reconnect with the needed permissions, or ask a workspace admin.")
    if isinstance(error, SimsonNotFound):
        return ServiceValidationError("That record no longer exists in Simson.")
    if isinstance(error, SimsonConflict):
        return HomeAssistantError("Simson changed this record at the same time. Try again.")
    return HomeAssistantError(f"Simson did not complete the request: {error}")


async def async_register_services(hass: HomeAssistant) -> None:
    async def call(service: ServiceCall) -> dict[str, Any]:
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        try:
            node, source, target = plan_call(runtime.coordinator.data, service.data["from_extension"], service.data["to_extension"])
            started = await runtime.api.start_call(runtime.coordinator.tenant_id, runtime.coordinator.site_id, node, source, target, timeout=service.data["timeout"], video=service.data["video"])
        except (ResolveError, SimsonError) as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()
        return {"call_id": started.get("id") or started.get("call_id"), "state": started.get("state")}

    async def hangup(service: ServiceCall) -> None:
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        known = runtime.coordinator.data.calls.get(service.data["call_id"])
        if known is None:
            raise ServiceValidationError("That call is not active.")
        try:
            await runtime.api.hang_up(runtime.coordinator.tenant_id, runtime.coordinator.site_id, known.id, known.revision)
        except SimsonError as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_CALL, call, schema=CALL_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_HANGUP, hangup, schema=HANGUP_SCHEMA)

    async def call_extension(service: ServiceCall) -> dict[str, Any]:
        """Call a phone from the default phone, so a script only needs to say who to ring."""
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        try:
            source = service.data.get("from_extension") or default_caller(runtime.coordinator.data, runtime.coordinator.default_extension)
            node, source_id, target_id = plan_call(runtime.coordinator.data, source, service.data["to_extension"])
            started = await runtime.api.start_call(runtime.coordinator.tenant_id, runtime.coordinator.site_id, node, source_id, target_id, timeout=service.data["timeout"], video=service.data["video"])
        except (ResolveError, SimsonError) as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()
        return {"call_id": started.get("id") or started.get("call_id"), "state": started.get("state"), "from_extension": source}

    async def run_preset(service: ServiceCall) -> dict[str, Any]:
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        try:
            automation = runnable(find_automation(runtime.coordinator.data, service.data["preset"]))
            result = await runtime.api.run_automation(runtime.coordinator.tenant_id, runtime.coordinator.site_id, automation.node_id, automation.id, automation.revision)
        except (ResolveError, SimsonError) as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()
        return {"preset": automation.name, "result": result if isinstance(result, dict) else {}}

    async def get_history(service: ServiceCall) -> dict[str, Any]:
        entry = _entry(hass, service.data)
        return {"calls": history_rows(entry.runtime_data.coordinator.data.calls, service.data["limit"])}

    async def get_extensions(service: ServiceCall) -> dict[str, Any]:
        data = _entry(hass, service.data).runtime_data.coordinator.data
        return {"extensions": [{"id": ext.id, "extension": ext.extension, "name": ext.name, "enabled": ext.enabled, "online": ext.online, "codecs": list(ext.codecs), "last_seen": ext.observed_at} for ext in data.extensions.values() if not ext.gateway]}

    async def get_numbers(service: ServiceCall) -> dict[str, Any]:
        data = _entry(hass, service.data).runtime_data.coordinator.data
        return {"numbers": [{"id": item.id, "number": item.number, "source": item.source} for item in data.numbers]}

    async def get_presets(service: ServiceCall) -> dict[str, Any]:
        data = _entry(hass, service.data).runtime_data.coordinator.data
        return {"presets": [{"id": item.id, "name": item.name, "enabled": item.enabled, "cooldown": item.cooldown, "video": item.video} for item in data.automations.values()]}

    async def get_targets(service: ServiceCall) -> dict[str, Any]:
        data = _entry(hass, service.data).runtime_data.coordinator.data
        return {
            "extensions": [{"id": item.id, "number": item.extension, "name": item.name, "node_id": item.node_id,
                            "online": item.online, "video": "H264" in item.codecs}
                           for item in data.extensions.values() if item.enabled and not item.gateway],
            "nodes": [{"id": node_id, "name": name} for node_id, name in data.nodes.items()],
            "presets": [{"id": item.id, "name": item.name, "node_id": item.node_id}
                        for item in data.automations.values() if item.enabled],
        }

    hass.services.async_register(DOMAIN, "get_targets", get_targets, schema=LIST_SCHEMA, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_CALL_EXTENSION, call_extension, schema=CALL_EXTENSION_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_GET_HISTORY, get_history, schema=HISTORY_SCHEMA, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_GET_EXTENSIONS, get_extensions, schema=LIST_SCHEMA, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_GET_NUMBERS, get_numbers, schema=LIST_SCHEMA, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_GET_PRESETS, get_presets, schema=LIST_SCHEMA, supports_response=SupportsResponse.ONLY)
