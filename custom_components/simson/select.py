"""Choose which phone Home Assistant calls from when a script does not say."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEFAULT_EXTENSION
from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import SimsonEntity, workspace_device
from .resolve import ResolveError, default_caller


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([SimsonDefaultPhone(entry.runtime_data.coordinator)])


class SimsonDefaultPhone(SimsonEntity, SelectEntity):
    """The calling phone for the Call buttons and for services that leave `from_extension` out."""

    _attr_translation_key = "default_phone"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SimsonCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.tenant_id}:{coordinator.site_id}_default_phone"
        self._attr_device_info = workspace_device(coordinator)

    def _usable(self) -> dict[str, str]:
        return {ext.extension: f"{ext.extension} {ext.name}".strip() for ext in self.coordinator.data.extensions.values() if ext.enabled and not ext.gateway}

    @property
    def options(self) -> list[str]:
        return [self._usable()[number] for number in sorted(self._usable(), key=lambda n: (len(n), n))]

    @property
    def current_option(self) -> str | None:
        try:
            return self._usable().get(default_caller(self.coordinator.data, self.coordinator.default_extension))
        except ResolveError:
            return None

    async def async_select_option(self, option: str) -> None:
        number = next((number for number, label in self._usable().items() if label == option), None)
        if number is None:
            return
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DEFAULT_EXTENSION: number})
        self.async_write_ha_state()
