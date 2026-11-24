"""Shared entity identity and site inventory discovery."""
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .protocol import DOMAIN


def site_device(site):
    return DeviceInfo(
        identifiers={(DOMAIN, site.site_id)}, name=site.entry.title,
        manufacturer="Architech Labs", entry_type=DeviceEntryType.SERVICE,
    )


def phone_device(site, phone):
    return DeviceInfo(
        identifiers={(DOMAIN, phone.id)}, via_device=(DOMAIN, site.site_id),
        name=phone.name, manufacturer="Architech Labs",
        model="SIP gateway" if phone.gateway else "SIP extension",
    )


def discover_phones(hass, entry, add_entities, factory):
    added = set()
    site = entry.runtime_data

    @callback
    def discover():
        current = (site.inventory or {}).get("phones", {})
        new = current.keys() - added
        if new:
            added.update(new)
            add_entities([entity for key in sorted(new) for entity in factory(current[key])])

    discover()
    entry.async_on_unload(async_dispatcher_connect(hass, site.inventory_signal, discover))


class SiteEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, site, key, name, *, phone=None, signals=None):
        self.site = site
        self.phone_id = phone.id if phone else None
        self.signals = signals or (site.signal,)
        self._attr_unique_id = f"{site.site_id}:{phone.id}:{key}" if phone else f"{site.site_id}:{key}"
        self._attr_name = name
        self._attr_device_info = phone_device(site, phone) if phone else site_device(site)

    @property
    def phone(self):
        return (self.site.inventory or {}).get("phones", {}).get(self.phone_id)

    @property
    def available(self):
        return self.phone_id is None or self.phone is not None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for signal in self.signals:
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self.async_write_ha_state))
