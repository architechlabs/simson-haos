"""Resolve only push-enabled mobile devices assigned to a Home Assistant user."""
import re

from .protocol import HA_ID

DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def companion_devices(hass):
    registrations = hass.data.get("mobile_app", {}).get("config_entries", {})
    devices = {}
    if not registrations or not hass.services.has_service("notify", "mobile_app"):
        return devices
    from homeassistant.components.mobile_app.util import supports_push

    for target, entry in registrations.items():
        data = entry.data
        user = data.get("user_id")
        device = data.get("device_id")
        if (
            not isinstance(user, str) or not HA_ID.fullmatch(user)
            or not isinstance(device, str) or not DEVICE_ID.fullmatch(device)
            or entry.disabled_by
            or str(data.get("os_name", "")).lower() not in ("ios", "android")
        ):
            continue
        try:
            if not supports_push(hass, target):
                continue
        except (AttributeError, KeyError, TypeError):
            continue
        name = str(data.get("device_name") or entry.title)
        devices.setdefault(user, {}).setdefault(device, (name[:80], target))
    return devices


async def active_users(hass):
    return {user.id: user for user in await hass.auth.async_get_users()
            if user.is_active and not user.system_generated and HA_ID.fullmatch(user.id)}
