"""One coordinator per workspace location: a single refresh feeds every entity."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SimsonApi, SimsonAuthError, SimsonError, SimsonPermissionError
from .const import BUS_EVENT, CONF_SITE_ID, CONF_TENANT_ID, DOMAIN, SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_IDLE
from .model import CallEvent, CallInfo, Workspace, build_extensions, diff_calls, interval_for, parse_calls, parse_runtime

_LOGGER = logging.getLogger(__name__)

type SimsonConfigEntry = ConfigEntry["SimsonRuntime"]


@dataclass
class SimsonRuntime:
    coordinator: "SimsonCoordinator"
    api: SimsonApi


class SimsonCoordinator(DataUpdateCoordinator[Workspace]):
    """Fetches the location snapshot, who is online and the call list together."""

    config_entry: SimsonConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SimsonConfigEntry, api: SimsonApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=SCAN_INTERVAL_IDLE))
        self.api = api
        self.tenant_id: str = entry.data[CONF_TENANT_ID]
        self.site_id: str = entry.data[CONF_SITE_ID]
        self._previous_calls: dict[str, CallInfo] | None = None
        self._listeners: list[Callable[[CallEvent], None]] = []

    def async_add_call_listener(self, listener: Callable[[CallEvent], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def _calls(self) -> dict[str, CallInfo]:
        try:
            dashboard = await self.api.call_dashboard(self.tenant_id)
        except SimsonPermissionError:
            return {}  # the user did not grant call history; everything else still works
        return {key: call for key, call in parse_calls(dashboard).items()}

    async def _async_update_data(self) -> Workspace:
        try:
            snapshot, presence, calls = await asyncio.gather(
                self.api.snapshot(self.tenant_id, self.site_id),
                self.api.presence(self.tenant_id, self.site_id),
                self._calls(),
            )
        except SimsonAuthError as error:
            raise ConfigEntryAuthFailed("Sign in to Simson again.") from error
        except SimsonError as error:
            raise UpdateFailed(str(error)) from error

        node, sip = parse_runtime(presence)
        workspace = Workspace(
            nodes={item["id"]: item.get("display_name", "") for item in snapshot.get("nodes", [])},
            extensions=build_extensions(snapshot, presence),
            presence_state=presence.get("state", "unknown"),
            media_node_id=node,
            sip=sip,
            calls=calls,
            active_calls=sum(1 for call in calls.values() if call.phase == "active"),
            total_calls=len(calls),
            answered_calls=sum(1 for call in calls.values() if call.connected_at),
        )
        for event in diff_calls(self._previous_calls, calls):
            self.hass.bus.async_fire(BUS_EVENT, {"event": event.kind, "call_id": event.call.id, "phase": event.call.phase, "connected_seconds": event.call.connected_seconds, "site_id": self.site_id})
            for listener in list(self._listeners):
                listener(event)
        self._previous_calls = calls
        self.update_interval = timedelta(seconds=interval_for(workspace, SCAN_INTERVAL_IDLE, SCAN_INTERVAL_ACTIVE))
        return workspace
