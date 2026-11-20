"""Is each phone registered right now?"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import SimsonEntity, extension_device


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def _add_new() -> None:
        fresh = [SimsonExtensionOnline(coordinator, ext_id) for ext_id in coordinator.data.extensions if ext_id not in known]
        known.update(entity.extension_id for entity in fresh)
        if fresh:
            async_add_entities(fresh)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class SimsonExtensionOnline(SimsonEntity, BinarySensorEntity):
    """On when the phone is registered. Unknown when the voice node is not observed."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "extension_online"

    def __init__(self, coordinator: SimsonCoordinator, extension_id: str) -> None:
        super().__init__(coordinator)
        self.extension_id = extension_id
        self._attr_unique_id = f"{extension_id}_online"
        self._attr_device_info = extension_device(coordinator, coordinator.data.extensions[extension_id])

    @property
    def available(self) -> bool:
        return super().available and self.extension_id in self.coordinator.data.extensions

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.extensions[self.extension_id].online

    @property
    def extra_state_attributes(self) -> dict:
        ext = self.coordinator.data.extensions[self.extension_id]
        # simson_extension marks entities the dashboard card can discover.
        return {"simson_extension": ext.extension, "name": ext.name, "enabled": ext.enabled, "gateway": ext.gateway, "endpoint_id": ext.id}
