"""Expose each installed scoped Simson automation as a native HA button."""
from pathlib import Path

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .automation import NAME, read_automation_key
from .cloud import PRIVATE_DIR
from .entity import SiteEntity
from .protocol import DOMAIN


def automation_names(site_id):
    directory = Path(PRIVATE_DIR) / site_id
    names = []
    try:
        for candidate in sorted(directory.iterdir())[:256]:
            if candidate.suffix == ".key" and NAME.fullmatch(candidate.stem):
                try:
                    read_automation_key(site_id, candidate.stem)
                except (OSError, ValueError):
                    continue
                names.append(candidate.stem)
    except OSError:
        return []
    return names[:64]


async def async_setup_entry(hass, entry, async_add_entities):
    names = await hass.async_add_executor_job(automation_names, entry.runtime_data.site_id)
    async_add_entities([RefreshInventory(entry.runtime_data), *[AutomationButton(entry.runtime_data, name) for name in names]])


class RefreshInventory(SiteEntity, ButtonEntity):
    _attr_icon = "mdi:refresh"

    def __init__(self, site):
        super().__init__(site, "refresh_presence", "Refresh extension status", signals=(site.inventory_signal,))

    async def async_press(self):
        if self.site.inventory_feed is not None:
            self.site.inventory_feed.request()


class AutomationButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:phone-outgoing"

    def __init__(self, site, name):
        self.site = site
        self.automation = name
        self._attr_name = name.replace("_", " ").replace("-", " ").capitalize()
        self._attr_unique_id = f"{site.site_id}:automation:{name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, site.site_id)}, name="Simson location",
            manufacturer="Architech Labs", entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self):
        await self.hass.services.async_call(DOMAIN, "trigger_automation", {
            "site_id": self.site.site_id, "automation": self.automation,
        }, blocking=True, context=self._context)
