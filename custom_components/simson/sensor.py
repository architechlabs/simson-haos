"""Workspace level sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import SimsonEntity, workspace_device


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([SimsonActiveCalls(coordinator), SimsonCallsInWindow(coordinator), SimsonVoiceStatus(coordinator)])


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
        return {"simson_calls": True, "calls": live}


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
        return {"sip_server": sip.get("server"), "sip_port": sip.get("port"), "sip_transport": sip.get("transport"), "sip_realm": sip.get("realm")}
