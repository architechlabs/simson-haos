"""A single event entity for call lifecycle changes: incoming, answered, ended, missed."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVENT_TYPES
from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import workspace_device
from .model import CallEvent


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([SimsonCallEvents(entry.runtime_data.coordinator)])


class SimsonCallEvents(EventEntity):
    """Fires for every call change, so automations can trigger on them."""

    _attr_has_entity_name = True
    _attr_translation_key = "calls"
    _attr_icon = "mdi:phone-log"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: SimsonCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.tenant_id}:{coordinator.site_id}_call_events"
        self._attr_device_info = workspace_device(coordinator)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.async_add_call_listener(self._handle))

    @callback
    def _handle(self, event: CallEvent) -> None:
        call = event.call
        self._trigger_event(event.kind, {
            "call_id": call.id, "phase": call.phase, "started_at": call.started_at, "connected_at": call.connected_at, "ended_at": call.ended_at, "connected_seconds": call.connected_seconds,
            "caller_extension": event.caller["extension"] if event.caller else None, "caller_name": event.caller["name"] if event.caller else None,
            "callee_extension": event.callee["extension"] if event.callee else None, "callee_name": event.callee["name"] if event.callee else None,
        })
        self.async_write_ha_state()
