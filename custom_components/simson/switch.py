"""Turn a phone extension on or off from Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SimsonError
from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import SimsonEntity, extension_device


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def _add_new() -> None:
        fresh = [SimsonExtensionEnabled(coordinator, ext_id) for ext_id, ext in coordinator.data.extensions.items() if ext_id not in known and not ext.gateway]
        known.update(entity.extension_id for entity in fresh)
        if fresh:
            async_add_entities(fresh)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class SimsonExtensionEnabled(SimsonEntity, SwitchEntity):
    """On when the phone may register and call. Turning it off signs it out of Simson."""

    _attr_translation_key = "extension_enabled"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SimsonCoordinator, extension_id: str) -> None:
        super().__init__(coordinator)
        self.extension_id = extension_id
        self._attr_unique_id = f"{extension_id}_enabled"
        self._attr_device_info = extension_device(coordinator, coordinator.data.extensions[extension_id])

    @property
    def available(self) -> bool:
        return super().available and self.extension_id in self.coordinator.data.extensions

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.extensions[self.extension_id].enabled

    async def _set(self, enabled: bool) -> None:
        ext = self.coordinator.data.extensions[self.extension_id]
        if ext.enabled == enabled:
            return
        try:
            await self.coordinator.api.update_extension(
                self.coordinator.tenant_id, self.coordinator.site_id, ext.id,
                display_name=ext.name, extension=ext.extension, codecs=list(ext.codecs), enabled=enabled, revision=ext.revision,
            )
        except SimsonError as error:
            raise HomeAssistantError(f"Simson could not change extension {ext.extension}: {error}") from error
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
