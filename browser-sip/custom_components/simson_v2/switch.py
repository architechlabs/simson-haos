"""Control Companion notifications per Simson location."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .entity import SiteEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Notifications(entry.runtime_data)])


class Notifications(SiteEntity, SwitchEntity):
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, site):
        super().__init__(site, "mobile_notifications", "Mobile call notifications", signals=(site.route_signal,))

    @property
    def is_on(self):
        return self.site.notifications_enabled

    async def set_enabled(self, enabled):
        actor = self._context.user_id if self._context else None
        if actor:
            user = await self.hass.auth.async_get_user(actor)
            if not user or not user.is_active or not user.is_admin:
                raise HomeAssistantError("Only a Home Assistant administrator may change notifications.")
        self.hass.config_entries.async_update_entry(self.site.entry, options={
            **self.site.entry.options, "notifications_enabled": enabled,
        })
        async_dispatcher_send(self.hass, self.site.route_signal)

    async def async_turn_on(self, **kwargs):
        await self.set_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.set_enabled(False)
