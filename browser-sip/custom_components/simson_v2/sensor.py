"""Stable site and extension telemetry for dashboards and automations."""
from datetime import datetime
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.core import callback

from .entity import SiteEntity, discover_phones

SITE_METRICS = {
    "connection": ("Integration", "mdi:connection"),
    "call_state": ("Call state", "mdi:phone"),
    "active_calls": ("Active calls", "mdi:phone-in-talk"),
    "connected_calls": ("Connected calls", "mdi:phone-check-outline"),
    "last_call": ("Last call event", "mdi:history"),
    "last_automation": ("Last automation", "mdi:robot"),
    "last_call_at": ("Last call event at", "mdi:history"),
    "inventory_updated": ("Presence checked at", "mdi:clock-outline"),
    "inventory_state": ("Presence status", "mdi:lan-connect"),
    "groups": ("Enabled phone groups", "mdi:account-group-outline"),
    "phones": ("Configured extensions", "mdi:dialpad"),
    "gateways": ("SIP gateways", "mdi:router-network"),
    "online": ("Registered extensions", "mdi:phone-check-outline"),
    "offline": ("Offline extensions", "mdi:phone-off-outline"),
    "unknown": ("Extensions with unknown status", "mdi:help-circle-outline"),
    "disabled": ("Disabled extensions", "mdi:phone-cancel-outline"),
    "media": ("Media servers", "mdi:server"),
    "fresh_media": ("Reachable media servers", "mdi:server-network"),
    "ringing": ("Ringing calls", "mdi:phone-ring-outline"),
    "answered_total": ("Observed answers", "mdi:phone-in-talk"),
    "missed_total": ("Observed missed calls", "mdi:phone-missed"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    site = entry.runtime_data
    async_add_entities([SiteSensor(site, key, name, icon) for key, (name, icon) in SITE_METRICS.items()])
    discover_phones(hass, entry, async_add_entities, lambda phone: [RegistrationSensor(site, phone)])
    contacts = set()

    @callback
    def sync_routes():
        new = set(site.routes) - contacts
        if new:
            contacts.update(new)
            async_add_entities([ContactSensor(site, endpoint) for endpoint in sorted(new)])

    sync_routes()
    entry.async_on_unload(async_dispatcher_connect(hass, site.route_signal, sync_routes))


class SiteSensor(SiteEntity, SensorEntity):
    def __init__(self, site, key, name, icon):
        signals = (site.inventory_signal,) if key in ("inventory_updated", "inventory_state", "groups", "phones", "gateways", "online", "offline", "unknown", "disabled", "media", "fresh_media") else (site.signal,)
        super().__init__(site, key, name, signals=signals)
        self.key = key
        self._attr_icon = icon
        if key in ("last_call_at", "inventory_updated"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def available(self):
        return self.key not in ("call_state", "active_calls", "connected_calls", "ringing") or self.site.connection == "connected"

    @property
    def native_value(self):
        key = self.key
        site = self.site
        inventory = site.inventory or {}
        if key == "connection":
            return site.connection
        if key in ("active_calls", "connected_calls", "call_state", "ringing"):
            calls = site.live_calls()
            if key == "active_calls":
                return len(calls)
            if key == "connected_calls":
                return sum(call["state"] == "answered" for call in calls)
            if key == "ringing":
                return sum(call["state"] == "ringing" for call in calls)
            return "ringing" if any(call["state"] == "ringing" for call in calls) else "answered" if calls else "idle"
        if key == "last_call":
            return site.last_call["state"] if site.last_call else "none"
        if key == "last_call_at":
            return datetime.fromisoformat(site.last_call["occurred_at"]) if site.last_call else None
        if key == "last_automation":
            return site.last_automation["status"] if site.last_automation else "none"
        if key == "inventory_state":
            return site.inventory_state
        if key == "inventory_updated":
            return site.inventory_updated_at
        if key in ("answered_total", "missed_total"):
            return site.journal.totals[key.removesuffix("_total")]
        if not inventory:
            return None
        phones = inventory["phones"].values()
        if key == "phones":
            return sum(not phone.gateway for phone in phones)
        if key == "gateways":
            return sum(phone.gateway for phone in phones)
        if key == "groups":
            return inventory["groups"]
        trusted = site.inventory_state in ("fresh", "partial")
        if key == "disabled":
            return sum(not phone.enabled for phone in phones if not phone.gateway)
        if key in ("online", "offline", "unknown"):
            if not trusted and key != "unknown":
                return None
            state = lambda phone: inventory["states"].get(phone.id, "unknown") if trusted else "unknown"
            return sum(state(phone) == key for phone in phones if phone.enabled and not phone.gateway)
        return inventory["media"].get("total_nodes" if key == "media" else "fresh_nodes") if trusted else None

    @property
    def extra_state_attributes(self):
        if self.key == "last_call" and self.site.last_call:
            return {key: self.site.last_call[key] for key in ("call_id", "endpoint_id", "extension", "occurred_at", "revision")}
        if self.key == "last_automation" and self.site.last_automation:
            return {key: self.site.last_automation[key] for key in ("automation", "event_id")}
        return None


class RegistrationSensor(SiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline", "unknown", "disabled"]
    _attr_icon = "mdi:phone-check-outline"

    def __init__(self, site, phone):
        super().__init__(site, "registration", "Registration", phone=phone, signals=(site.inventory_signal,))

    @property
    def native_value(self):
        if not self.phone:
            return None
        if not self.phone.enabled:
            return "disabled"
        if self.site.inventory_state not in ("fresh", "partial"):
            return "unknown"
        return self.site.inventory["states"].get(self.phone_id, "unknown")

    @property
    def extra_state_attributes(self):
        phone = self.phone
        if phone:
            return {
                "extension": phone.extension, "endpoint_id": phone.id, "group_id": phone.group,
                "video_capable": phone.video, "sip_credentials_configured": phone.credentials_ready,
                "is_gateway": phone.gateway, "provisioning_status": phone.configuration,
            }
        return None


class ContactSensor(SiteSensor):
    def __init__(self, site, endpoint):
        super().__init__(site, f"contact:{endpoint}", f"Extension {site.routes[endpoint]['extension']} contact", "mdi:account-voice")
        self.endpoint = endpoint
        self.signals = (site.route_signal,)

    @property
    def native_value(self):
        return "assigned" if self.endpoint in self.site.routes else "unassigned"

    @property
    def extra_state_attributes(self):
        route = self.site.routes.get(self.endpoint)
        return {"endpoint_id": self.endpoint, "extension": route["extension"], "phones": len(route["devices"])} if route else None
