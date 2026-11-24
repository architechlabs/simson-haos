"""Press a button to call a phone, or to run a call preset such as a doorbell flow."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SimsonError
from .coordinator import SimsonConfigEntry, SimsonCoordinator
from .entity import SimsonEntity, extension_device, workspace_device
from .resolve import ResolveError, default_caller, find_automation, plan_call, runnable


async def async_setup_entry(hass: HomeAssistant, entry: SimsonConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def _add_new() -> None:
        fresh: list[ButtonEntity] = []
        for ext_id, ext in coordinator.data.extensions.items():
            if ext.gateway or f"call:{ext_id}" in known:
                continue
            known.add(f"call:{ext_id}")
            fresh.append(SimsonCallButton(coordinator, ext_id))
        for automation_id in coordinator.data.automations:
            if f"preset:{automation_id}" in known:
                continue
            known.add(f"preset:{automation_id}")
            fresh.append(SimsonPresetButton(coordinator, automation_id))
        if fresh:
            async_add_entities(fresh)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class SimsonCallButton(SimsonEntity, ButtonEntity):
    """Calls this phone from the default phone. Press it from a dashboard or an automation."""

    _attr_translation_key = "call_extension"

    def __init__(self, coordinator: SimsonCoordinator, extension_id: str) -> None:
        super().__init__(coordinator)
        self.extension_id = extension_id
        self._attr_unique_id = f"{extension_id}_call"
        self._attr_device_info = extension_device(coordinator, coordinator.data.extensions[extension_id])

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and self.extension_id in data.extensions and data.extensions[self.extension_id].enabled and data.media_node_id is not None

    async def async_press(self) -> None:
        data = self.coordinator.data
        target = data.extensions[self.extension_id]
        try:
            source = default_caller(data, self.coordinator.default_extension, exclude_id=target.id)
            node, source_id, target_id = plan_call(data, source, target.extension)
            await self.coordinator.api.start_call(self.coordinator.tenant_id, self.coordinator.site_id, node, source_id, target_id)
        except (ResolveError, SimsonError) as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()


class SimsonPresetButton(SimsonEntity, ButtonEntity):
    """Runs a saved call preset, for example ringing the kitchen when the front door bell is pressed."""

    _attr_translation_key = "run_preset"

    def __init__(self, coordinator: SimsonCoordinator, automation_id: str) -> None:
        super().__init__(coordinator)
        self.automation_id = automation_id
        automation = coordinator.data.automations[automation_id]
        self._attr_unique_id = f"{automation_id}_preset"
        self._attr_name = automation.name
        self._attr_device_info = workspace_device(coordinator)

    @property
    def available(self) -> bool:
        automation = self.coordinator.data.automations.get(self.automation_id)
        return super().available and automation is not None and automation.enabled

    async def async_press(self) -> None:
        try:
            automation = runnable(find_automation(self.coordinator.data, self.automation_id))
            await self.coordinator.api.run_automation(self.coordinator.tenant_id, self.coordinator.site_id, automation.node_id, automation.id, automation.revision)
        except (ResolveError, SimsonError) as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()
