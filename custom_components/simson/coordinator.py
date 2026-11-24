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
from .const import (
    BUS_EVENT,
    BUS_EXTENSION_EVENT,
    CONF_DEFAULT_EXTENSION,
    CONF_SCAN_ACTIVE,
    CONF_SCAN_IDLE,
    CONF_SITE_ID,
    CONF_TENANT_ID,
    DOMAIN,
    SCAN_INTERVAL_ACTIVE,
    SCAN_INTERVAL_IDLE,
    SLOW_REFRESH_EVERY,
)
from .stream import EventStreamer
from .model import (
    Automation,
    CallEvent,
    CallInfo,
    CarrierNumber,
    Summary,
    Workspace,
    build_extensions,
    diff_calls,
    diff_presence,
    interval_for,
    parse_automations,
    parse_calls,
    parse_numbers,
    parse_runtime,
    parse_summary,
)

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
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_IDLE, SCAN_INTERVAL_IDLE)))
        self.api = api
        self.tenant_id: str = entry.data[CONF_TENANT_ID]
        self.site_id: str = entry.data[CONF_SITE_ID]
        self._previous_calls: dict[str, CallInfo] | None = None
        self._previous_extensions = None
        self._call_listeners: list[Callable[[CallEvent], None]] = []
        self._tick = 0
        self._automations: dict[str, Automation] = {}
        self._numbers: list[CarrierNumber] = []
        self.live = False  # True while the live event stream is connected
        self.streamer = EventStreamer(hass, api, self.tenant_id, on_event=self._on_live, on_state=self._on_live_state, on_auth_failed=self._on_stream_auth)

    # ---- live events -----------------------------------------------------

    def _announce(self, event: CallEvent, source: str) -> None:
        call = event.call
        payload = {"event": event.kind, "call_id": call.id, "phase": call.phase, "connected_seconds": call.connected_seconds, "site_id": self.site_id, "source": source}
        for role, party in (("caller", event.caller), ("callee", event.callee)):
            payload[f"{role}_extension"] = party["extension"] if party else None
            payload[f"{role}_name"] = party["name"] if party else None
        self.hass.bus.async_fire(BUS_EVENT, payload)
        for listener in list(self._call_listeners):
            listener(event)

    def _on_live(self, event: CallEvent) -> None:
        self._announce(event, "stream")
        # Refresh counters and the call list soon; several events in a burst share one refresh.
        self.hass.async_create_task(self.async_request_refresh())

    def _on_live_state(self, connected: bool) -> None:
        self.live = connected
        _LOGGER.debug("Simson live events %s", "connected" if connected else "disconnected")

    def _on_stream_auth(self) -> None:
        self.config_entry.async_start_reauth(self.hass)

    # ---- options ---------------------------------------------------------

    @property
    def default_extension(self) -> str | None:
        return self.config_entry.options.get(CONF_DEFAULT_EXTENSION)

    @property
    def _idle(self) -> int:
        return int(self.config_entry.options.get(CONF_SCAN_IDLE, SCAN_INTERVAL_IDLE))

    @property
    def _active(self) -> int:
        return int(self.config_entry.options.get(CONF_SCAN_ACTIVE, SCAN_INTERVAL_ACTIVE))

    def async_add_call_listener(self, listener: Callable[[CallEvent], None]) -> Callable[[], None]:
        self._call_listeners.append(listener)
        return lambda: self._call_listeners.remove(listener)

    # ---- fetching ----------------------------------------------------------

    async def _dashboard(self) -> dict:
        try:
            return await self.api.call_dashboard(self.tenant_id)
        except SimsonPermissionError:
            return {}  # the user did not grant call history; everything else still works

    async def _slow_data(self, nodes: list[str]) -> None:
        """Things that rarely change are refreshed every few polls, not every poll."""
        results = await asyncio.gather(
            *(self.api.automations(self.tenant_id, self.site_id, node) for node in nodes),
            self.api.numbers(self.tenant_id, self.site_id),
            return_exceptions=True,
        )
        *lists, numbers = results
        good = [item for item in lists if isinstance(item, dict)]
        if good or not nodes:
            # Each automation item already carries its node id.
            self._automations = parse_automations(good)
        if isinstance(numbers, list):
            self._numbers = parse_numbers(numbers)
        for failure in (*lists, numbers):
            if isinstance(failure, SimsonAuthError):
                raise failure

    async def _async_update_data(self) -> Workspace:
        try:
            snapshot, presence, dashboard = await asyncio.gather(
                self.api.snapshot(self.tenant_id, self.site_id),
                self.api.presence(self.tenant_id, self.site_id),
                self._dashboard(),
            )
            nodes = [item["id"] for item in snapshot.get("nodes", []) if item.get("desired_enabled", True)]
            if self._tick % SLOW_REFRESH_EVERY == 0:
                await self._slow_data(nodes)
            self._tick += 1
        except SimsonAuthError as error:
            raise ConfigEntryAuthFailed("Sign in to Simson again.") from error
        except SimsonError as error:
            raise UpdateFailed(str(error)) from error

        node, sip = parse_runtime(presence)
        calls = parse_calls(dashboard)
        extensions = build_extensions(snapshot, presence)
        workspace = Workspace(
            nodes={item["id"]: item.get("display_name", "") for item in snapshot.get("nodes", [])},
            extensions=extensions,
            automations=self._automations,
            numbers=self._numbers,
            presence_state=presence.get("state", "unknown"),
            media_node_id=node,
            sip=sip,
            calls=calls,
            summary=parse_summary(dashboard) if dashboard else Summary(),
            active_calls=sum(1 for call in calls.values() if call.phase == "active"),
            total_calls=len(calls),
            answered_calls=sum(1 for call in calls.values() if call.connected_at),
        )
        # While the live stream is connected it reports every change; polling only fills in when it is not.
        for event in diff_calls(self._previous_calls, calls):
            if not self.live:
                self._announce(event, "poll")
        for changed, change in diff_presence(self._previous_extensions, extensions):
            self.hass.bus.async_fire(BUS_EXTENSION_EVENT, {"change": change, "extension": changed.extension, "name": changed.name, "endpoint_id": changed.id, "site_id": self.site_id})
        self._previous_calls = calls
        self._previous_extensions = extensions
        self.update_interval = timedelta(seconds=interval_for(workspace, self._idle, self._active))
        return workspace
