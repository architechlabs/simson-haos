"""Live connectivity and call conditions for Home Assistant automations."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import SiteEntity, discover_phones


async def async_setup_entry(hass, entry, async_add_entities):
    site = entry.runtime_data
    async_add_entities([
        Condition(site, "cloud_connected", "Cloud connected", BinarySensorDeviceClass.CONNECTIVITY),
        Condition(site, "site_ringing", "Incoming call"),
        Condition(site, "site_in_call", "Call active"),
        Condition(site, "media_ready", "Media reachable", BinarySensorDeviceClass.CONNECTIVITY),
    ])
    discover_phones(hass, entry, async_add_entities, lambda phone: [
        Condition(site, "registered", "Registered", BinarySensorDeviceClass.CONNECTIVITY, phone),
        Condition(site, "ringing", "Ringing", phone=phone),
        Condition(site, "in_call", "In call", phone=phone),
    ])


class Condition(SiteEntity, BinarySensorEntity):
    def __init__(self, site, key, name, device_class=None, phone=None):
        super().__init__(site, key, name, phone=phone, signals=(site.signal, site.inventory_signal))
        self.key = key
        self._attr_device_class = device_class

    @property
    def registration(self):
        return (self.site.inventory or {}).get("states", {}).get(self.phone_id, "unknown")

    @property
    def available(self):
        if not super().available:
            return False
        if self.key in ("registered", "media_ready"):
            return self.site.inventory_state in ("fresh", "partial") and (
                self.registration in ("online", "offline", "disabled") if self.key == "registered" else True
            )
        return self.key == "cloud_connected" or self.site.connection == "connected"

    @property
    def is_on(self):
        if self.key == "cloud_connected":
            return self.site.connection == "connected"
        if self.key == "registered":
            return self.registration == "online"
        if self.key == "media_ready":
            return (self.site.inventory or {}).get("media", {}).get("fresh_nodes", 0) > 0
        state = "ringing" if self.key in ("ringing", "site_ringing") else "answered"
        return any(item["state"] == state and (self.phone_id is None or item["endpoint_id"] == self.phone_id)
                   for item in self.site.live_calls())
