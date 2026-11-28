"""Workspace level sensors."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import SimsonEntity, workspace_device
from .const import CONF_BROWSER_EXTENSION, CONF_SITE_NAME, DEFAULT_BROWSER_EXTENSION
from .model import Workspace


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([
        SimsonActiveCalls(coordinator), SimsonCallsInWindow(coordinator), SimsonVoiceStatus(coordinator),
        SimsonWorkspaceMetric(coordinator, "registered_phones", _registered_extensions),
        SimsonWorkspaceMetric(coordinator, "outbound_routes", lambda data: len(data.outbound_routes)),
        SimsonWorkspaceMetric(coordinator, "answered_calls", lambda data: data.summary.answered if data.summary.window_days else None),
        SimsonWorkspaceMetric(coordinator, "connected_seconds", lambda data: data.summary.connected_seconds if data.summary.window_days else None),
    ])


def _registered_extensions(data: Workspace) -> int | None:
    if data.presence_state != "fresh":
        return None
    return sum(ext.online is True for ext in data.extensions.values() if not ext.gateway)


class _WorkspaceSensor(SimsonEntity, SensorEntity):
    def __init__(self, coordinator: SimsonCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.tenant_id}:{coordinator.site_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = workspace_device(coordinator)


class SimsonActiveCalls(_WorkspaceSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimsonCoordinator) -> None:
        super().__init__(coordinator, "active_calls")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.active_calls

    @property
    def extra_state_attributes(self) -> dict:
        # simson_calls marks this sensor for the dashboard card; calls lists the live ones.
        live = [{"id": c.id, "phase": c.phase, "started_at": c.started_at, "connected_at": c.connected_at} for c in self.coordinator.data.calls.values() if c.phase in ("requesting", "ringing", "active")]
        return {"simson_calls": True, "calls": live, "site_id": self.coordinator.site_id,
                "config_entry_id": self.coordinator.config_entry.entry_id}


class SimsonWorkspaceMetric(_WorkspaceSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimsonCoordinator, key: str, measure: Callable[[Workspace], int | None]) -> None:
        super().__init__(coordinator, key)
        self._measure = measure
        if key == "connected_seconds":
            self._attr_native_unit_of_measurement = "s"

    @property
    def native_value(self) -> int | None:
        return self._measure(self.coordinator.data)


class SimsonCallsInWindow(_WorkspaceSensor):
    """Calls in the recent history window, with how many were answered."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimsonCoordinator) -> None:
        super().__init__(coordinator, "recent_calls")

    @property
    def native_value(self) -> int:
        return self.coordinator.data.total_calls

    @property
    def extra_state_attributes(self) -> dict:
        return {"answered": self.coordinator.data.answered_calls}


class SimsonVoiceStatus(_WorkspaceSensor):
    """Whether the location's voice service is being observed, plus phone connection details."""

    def __init__(self, coordinator: SimsonCoordinator) -> None:
        super().__init__(coordinator, "voice_status")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.presence_state

    @property
    def extra_state_attributes(self) -> dict:
        sip = self.coordinator.data.sip or {}
        browser_sip = self.coordinator.data.browser_sip or {}
        entry = self.coordinator.config_entry
        number = entry.options.get(CONF_BROWSER_EXTENSION, DEFAULT_BROWSER_EXTENSION)
        endpoint = next((ext for ext in self.coordinator.data.extensions.values()
                         if ext.extension == number and ext.enabled and not ext.gateway), None)
        return {"simson_voice": True, "config_entry_id": entry.entry_id, "site_id": self.coordinator.site_id,
                "site_name": entry.data.get(CONF_SITE_NAME), "browser_extension": number, "browser_endpoint_ready": endpoint is not None,
                "browser_video": bool(endpoint and "H264" in endpoint.codecs),
                "browser_registration_realm": endpoint.registration_realm if endpoint else None,
                "outbound_routes": [{"name": route["name"], "prefix": route["prefix"]} for route in self.coordinator.data.outbound_routes
                                    if number in route["extensions"]],
                "sip_server": sip.get("server"), "sip_port": sip.get("port"), "sip_transport": sip.get("transport"),
                "sip_realm": sip.get("realm"), "browser_realm": browser_sip.get("realm"), "sip_wss_port": browser_sip.get("port")}
