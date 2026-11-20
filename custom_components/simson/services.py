"""simson.* services: call, hang up and manage extensions from automations."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import SimsonConflict, SimsonError, SimsonNotFound, SimsonPermissionError, SimsonPlanError
from .const import (
    DOMAIN,
    SERVICE_CALL,
    SERVICE_CREATE_EXTENSION,
    SERVICE_DELETE_EXTENSION,
    SERVICE_HANGUP,
    SERVICE_RESET_PASSWORD,
)
from .coordinator import SimsonConfigEntry
from .credential import CredentialError
from .resolve import ResolveError, find_extension, phone_settings, plan_call, validate_new_extension

_LOGGER = logging.getLogger(__name__)

_TARGET = {vol.Optional("config_entry_id"): cv.string}
CALL_SCHEMA = vol.Schema({**_TARGET, vol.Required("from_extension"): cv.string, vol.Required("to_extension"): cv.string, vol.Optional("video", default=False): cv.boolean, vol.Optional("timeout", default=30): vol.All(vol.Coerce(int), vol.Range(min=10, max=120))})
HANGUP_SCHEMA = vol.Schema({**_TARGET, vol.Required("call_id"): cv.string})
CREATE_SCHEMA = vol.Schema({**_TARGET, vol.Required("name"): cv.string, vol.Required("extension"): cv.string, vol.Optional("notify", default=True): cv.boolean})
EXTENSION_SCHEMA = vol.Schema({**_TARGET, vol.Required("extension"): cv.string})
RESET_SCHEMA = vol.Schema({**_TARGET, vol.Required("extension"): cv.string, vol.Optional("notify", default=True): cv.boolean})


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
    if isinstance(error, CredentialError):
        return HomeAssistantError("The new phone password could not be read safely. Nothing was shown. Try again.")
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

    async def _issue(entry: SimsonConfigEntry, endpoint_id: str, credential_revision: int, extension: str, notify: bool, title: str) -> dict[str, Any]:
        runtime = entry.runtime_data
        password = await runtime.api.issue_password(runtime.coordinator.tenant_id, runtime.coordinator.site_id, endpoint_id, credential_revision)
        details = phone_settings(runtime.coordinator.data, extension, password)
        if notify:
            lines = "\n".join(f"- **{label}:** {details[key]}" for label, key in (("Server", "server"), ("Port", "port"), ("Transport", "transport"), ("Username", "username"), ("Password", "password")) if details.get(key) is not None)
            persistent_notification.async_create(hass, f"Enter these in the SIP phone. The password is shown only once.\n\n{lines}", title=title, notification_id=f"simson_{endpoint_id}")
        return details

    async def create_extension(service: ServiceCall) -> dict[str, Any]:
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        try:
            number, name = validate_new_extension(runtime.coordinator.data, service.data["extension"], service.data["name"])
            created = await runtime.api.create_extension(runtime.coordinator.tenant_id, runtime.coordinator.site_id, name, number)
            details = await _issue(entry, created["id"], 0, number, service.data["notify"], f"Simson phone {number} created")
        except (ResolveError, SimsonError, CredentialError) as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()
        return {**details, "endpoint_id": created["id"]}

    async def reset_password(service: ServiceCall) -> dict[str, Any]:
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        try:
            ext = find_extension(runtime.coordinator.data, service.data["extension"])
            details = await _issue(entry, ext.id, ext.credential_revision, ext.extension, service.data["notify"], f"Simson phone {ext.extension} password reset")
        except (ResolveError, SimsonError, CredentialError) as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()
        return {**details, "endpoint_id": ext.id}

    async def delete_extension(service: ServiceCall) -> None:
        entry = _entry(hass, service.data)
        runtime = entry.runtime_data
        try:
            ext = find_extension(runtime.coordinator.data, service.data["extension"])
            await runtime.api.delete_extension(runtime.coordinator.tenant_id, runtime.coordinator.site_id, ext.id, ext.revision)
        except (ResolveError, SimsonError) as error:
            raise _explain(error) from error
        await runtime.coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_CALL, call, schema=CALL_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_HANGUP, hangup, schema=HANGUP_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_EXTENSION, create_extension, schema=CREATE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_RESET_PASSWORD, reset_password, schema=RESET_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_EXTENSION, delete_extension, schema=EXTENSION_SCHEMA)
