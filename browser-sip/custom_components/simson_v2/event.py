"""Event entities emit transitions once; they never synthesize a call on load."""
from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .entity import site_device
from .protocol import STATES


async def async_setup_entry(hass, entry, async_add_entities):
    site = entry.runtime_data
    async_add_entities([
        Transition(site, "call_events", "Call lifecycle", "mdi:phone-log", site.call_signal, STATES),
        Transition(site, "automation_events", "Automation dispatch", "mdi:lightning-bolt", site.automation_signal, ("queued",)),
        Transition(site, "registration_events", "Extension registration", "mdi:lan-connect", site.registration_signal, ("online", "offline")),
        Transition(site, "notification_events", "Mobile notifications", "mdi:bell-ring-outline", site.notification_signal,
                   ("requested", "clear_requested", "delivery_failed")),
    ])


class Transition(EventEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, site, key, name, icon, signal, states):
        self.signal = signal
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{site.site_id}:{key}"
        self._attr_event_types = list(states)
        self._attr_device_info = site_device(site)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, self.signal, self._receive))

    @callback
    def _receive(self, value):
        event = value.get("state") or value["status"]
        self._trigger_event(event, {key: v for key, v in value.items() if key not in ("state", "status")})
        self.async_write_ha_state()
