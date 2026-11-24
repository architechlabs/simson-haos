"""Read existing site inventory and presence with bounded, staggered requests."""
from asyncio import Event, wait_for
from dataclasses import dataclass
from datetime import datetime, timezone
from random import uniform
from time import monotonic

from homeassistant.helpers.dispatcher import async_dispatcher_send

from .cloud import CloudUnavailable, Reauthorize, api_path, cloud_get
from .protocol import extension, uuid_text

PRESENCE_STATES = ("online", "offline", "unknown", "disabled")
PRESENCE_QUALITY = ("fresh", "partial", "unavailable", "unknown")


@dataclass(frozen=True)
class Phone:
    id: str
    name: str
    extension: str
    enabled: bool
    gateway: bool
    credentials_ready: bool
    video: bool
    group: str | None
    configuration: str


def project_catalog(body, tenant, site):
    identity = body["site"]
    if identity["id"] != site or identity["tenant_id"] != tenant:
        raise ValueError("Inventory belongs to another site")
    endpoints, groups = body["endpoints"], body["nodes"]
    if not isinstance(endpoints, list) or len(endpoints) > 512 or not isinstance(groups, list) or len(groups) > 3:
        raise ValueError("Invalid site inventory")
    phones = {}
    for phone in endpoints:
        if phone["site_id"] != site or phone["tenant_id"] != tenant:
            raise ValueError("Endpoint belongs to another site")
        if phone.get("retired"):
            continue
        key = uuid_text(phone["id"])
        name = phone["display_name"]
        node = phone.get("node_id")
        codecs = phone["codecs"]
        if not isinstance(name, str) or not name.isprintable() or not isinstance(codecs, list) or len(codecs) > 4 or key in phones:
            raise ValueError("Invalid endpoint metadata")
        phones[key] = Phone(
            key, name[:80], extension(phone["extension"]), phone.get("desired_enabled") is True,
            phone.get("gateway") is True, phone.get("credential_configured") is True,
            "H264" in codecs, uuid_text(node) if node else None,
            phone["provisioning_state"] if phone.get("provisioning_state") in
            ("applied", "disabled", "pending", "failed", "unassigned") else "unknown",
        )
    enabled_groups = sum(node.get("desired_enabled") is True for node in groups if not node.get("retired"))
    return phones, enabled_groups


def project_presence(body, phones):
    if not isinstance(body["endpoints"], list) or len(body["endpoints"]) > 512:
        raise ValueError("Invalid presence inventory")
    result = {}
    for row in body["endpoints"]:
        key = uuid_text(row["endpoint_id"])
        if key in phones:
            if key in result or row["state"] not in PRESENCE_STATES:
                raise ValueError("Invalid extension presence")
            result[key] = row["state"]
    quality = body["state"]
    metrics = {key: body[key] for key in ("total_nodes", "expected_nodes", "fresh_nodes")}
    if quality not in PRESENCE_QUALITY or any(type(value) is not int or not 0 <= value <= 64 for value in metrics.values()):
        raise ValueError("Invalid media presence")
    if not 0 <= metrics["fresh_nodes"] <= metrics["expected_nodes"] <= metrics["total_nodes"]:
        raise ValueError("Invalid media totals")
    return quality, result, metrics


class InventoryFeed:
    def __init__(self, site, cloud):
        self.site = site
        self.cloud = cloud
        self.path = api_path(site.entry.data["tenant_id"], site.site_id)
        self.next_catalog = 0
        self.wakeup = Event()
        self.last_requested = 0

    def request(self):
        if monotonic() - self.last_requested >= 5:
            self.last_requested = monotonic()
            self.next_catalog = 0
            self.wakeup.set()

    async def run(self):
        try:
            await wait_for(self.wakeup.wait(), uniform(.1, 2.5))
        except TimeoutError:
            pass
        while self.site.connection != "sign_in_required":
            self.wakeup.clear()
            try:
                await self.sample()
            except Reauthorize:
                # Authentication recovery and grant revocation are owned by the event feed.
                self.site.inventory_state = "unavailable"
                async_dispatcher_send(self.site.hass, self.site.inventory_signal)
            except (CloudUnavailable, KeyError, TypeError, ValueError, AttributeError):
                self.site.inventory_state = "unavailable"
                async_dispatcher_send(self.site.hass, self.site.inventory_signal)
            try:
                await wait_for(self.wakeup.wait(), uniform(23, 31))
            except TimeoutError:
                pass

    async def sample(self):
        site = self.site
        access = await self.cloud.access()
        previous = site.inventory
        if previous is None or monotonic() >= self.next_catalog:
            body = await cloud_get(site.hass, f"{self.path}/snapshot", access, 2 << 20)
            phones, groups = project_catalog(body, site.entry.data["tenant_id"], site.site_id)
            self.next_catalog = monotonic() + 240
        else:
            phones, groups = previous["phones"], previous["groups"]
        try:
            body = await cloud_get(site.hass, f"{self.path}/presence", access, 512 << 10)
            quality, states, media = project_presence(body, phones)
        except (CloudUnavailable, KeyError, TypeError, ValueError, AttributeError):
            quality, states, media = "unavailable", {}, {}
        site.inventory = {"phones": phones, "groups": groups, "states": states, "media": media}
        site.inventory_state = quality
        if quality in ("fresh", "partial"):
            site.inventory_updated_at = datetime.now(timezone.utc)
        async_dispatcher_send(site.hass, site.inventory_signal)
        if previous and quality in ("fresh", "partial"):
            for endpoint, state in states.items():
                old = previous["states"].get(endpoint)
                if old in ("online", "offline") and state in ("online", "offline") and state != old:
                    payload = {
                        "site_id": site.site_id, "endpoint_id": endpoint, "state": state,
                        "previous_state": old, "extension": phones[endpoint].extension,
                    }
                    site.hass.bus.async_fire("simson_v2_registration", payload)
                    async_dispatcher_send(site.hass, site.registration_signal, payload)
