"""Home Assistant automations can ring a user's assigned SIP extension."""

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .companion import active_users
from .protocol import DOMAIN, HA_ID
from .transport import get_site


def register_user_calls(hass):
    async def call_user(call):
        site = get_site(hass, call.data["site_id"])
        if site is None:
            raise ServiceValidationError("Choose a linked Simson location.")
        user_id = call.data["user_id"]
        if user_id not in await active_users(hass):
            raise ServiceValidationError("Choose an active Home Assistant user.")
        phones = (site.inventory or {}).get("phones", {})
        targets = []
        for endpoint, route in site.routes.items():
            phone = phones.get(endpoint)
            if (route["user_id"] == user_id and phone and phone.enabled and not phone.gateway
                    and phone.extension == route["extension"]):
                targets.append(phone.extension)
        wanted = call.data.get("extension")
        if wanted:
            targets = [target for target in targets if target == wanted]
        if len(targets) != 1:
            raise ServiceValidationError("Assign an enabled SIP extension to this user, or specify which assigned extension to ring.")

        entries = [entry for entry in hass.config_entries.async_entries("simson")
                   if entry.data.get("tenant_id") == site.entry.data["tenant_id"]
                   and entry.data.get("site_id") == site.site_id and getattr(entry, "runtime_data", None)]
        if len(entries) != 1 or not hass.services.has_service("simson", "call_extension"):
            raise ServiceValidationError("Link this location with the Simson integration to use its phone-to-phone calling.")
        payload = {"config_entry_id": entries[0].entry_id, "to_extension": targets[0], "video": call.data["video"]}
        if "from_extension" in call.data:
            payload["from_extension"] = call.data["from_extension"]
        return await hass.services.async_call(
            "simson", "call_extension", payload, blocking=True, context=call.context, return_response=True,
        )

    hass.services.async_register(DOMAIN, "call_user", call_user, schema=vol.Schema({
        vol.Required("site_id"): str,
        vol.Required("user_id"): vol.Match(HA_ID.pattern + r"\Z"),
        vol.Optional("extension"): vol.Match(r"[1-9][0-9]{1,7}\Z"),
        vol.Optional("from_extension"): vol.Match(r"[1-9][0-9]{1,7}\Z"),
        vol.Optional("video", default=False): bool,
    }), supports_response=SupportsResponse.OPTIONAL)
