"""Keep call events and notification delivery local to the selected HA site."""
from asyncio import Lock, sleep
from collections import OrderedDict
from datetime import datetime, timezone
from time import monotonic

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from urllib.parse import urlencode

from .companion import active_users, companion_devices
from .journal import Journal
from .protocol import DOMAIN, MAX_CALLS


class Site:
    def __init__(self, hass, entry, store=None, checkpoint=None):
        self.hass = hass
        self.entry = entry
        self.site_id = entry.data["site_id"]
        self.calls = OrderedDict()
        self.store = store
        self.journal = Journal(entry.data["tenant_id"], self.site_id, checkpoint)
        self.last_call = self.journal.last
        self.last_automation = None
        self.connection = "connecting"
        self.inventory = None
        self.inventory_state = "starting"
        self.inventory_updated_at = None
        self.inventory_feed = None
        self.pending_rings = {}
        self.notification_tasks = set()
        self.deliveries = {}
        self.delivery_locks = {}
        self.pickup_watchers = 0
        self.expiry_timer = None
        self.route_signal = f"{DOMAIN}_routes_{self.site_id}"
        self.signal = f"{DOMAIN}_events_{self.site_id}"
        self.inventory_signal = f"{DOMAIN}_inventory_{self.site_id}"
        self.call_signal = f"{DOMAIN}_calls_{self.site_id}"
        self.automation_signal = f"{DOMAIN}_automation_{self.site_id}"
        self.notification_signal = f"{DOMAIN}_notification_{self.site_id}"
        self.registration_signal = f"{DOMAIN}_registration_{self.site_id}"
        for event in self.journal.calls.values():
            # Only recover a previously answered call. A saved ring cannot wake a phone.
            if event["state"] == "answered":
                self.cache_call(event)

    @property
    def routes(self):
        return self.entry.options.get("routes", {})

    @property
    def notifications_enabled(self):
        return self.entry.options.get("notifications_enabled", True) is True

    def save_soon(self):
        if self.store is not None:
            self.store.async_delay_save(self.journal.data, 1)

    async def flush(self):
        if self.store is not None:
            await self.store.async_save(self.journal.data())

    def cache_call(self, event):
        call_id = event["call_id"]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(event["occurred_at"])).total_seconds()
        ttl = (45 if event["state"] == "ringing" else 3600) - max(0, age)
        if ttl > 0:
            self.calls[call_id] = (event, monotonic() + ttl)
        else:
            self.calls.pop(call_id, None)

    def schedule_expiry(self):
        self.stop_expiry()
        now = monotonic()
        next_expiry = min((expiry for event, expiry in self.calls.values()
                           if expiry > now and event["state"] in ("ringing", "answered")), default=None)
        if next_expiry is not None:
            self.expiry_timer = self.hass.loop.call_later(next_expiry - now, self.expire)

    def expire(self):
        self.expiry_timer = None
        async_dispatcher_send(self.hass, self.signal)
        self.schedule_expiry()

    def stop_expiry(self):
        if self.expiry_timer is not None:
            self.expiry_timer.cancel()
            self.expiry_timer = None

    def live_calls(self):
        now = monotonic()
        return [event for event, expires in self.calls.values()
                if expires > now and event["state"] in ("ringing", "answered")]

    async def ingest(self, event, *, replayed=False, silent=False):
        call_id = event["call_id"]
        if not self.journal.record(event):
            return False
        self.cache_call(event)
        while len(self.calls) > MAX_CALLS:
            evicted, _ = self.calls.popitem(last=False)
            self.deliveries.pop(evicted, None)
            self.delivery_locks.pop(evicted, None)
            self.pending_rings.pop(evicted, None)
        self.last_call = self.journal.last
        self.schedule_expiry()
        self.save_soon()
        if not silent and not (replayed and event["state"] == "ringing"):
            self.emit_call(event, replayed)
        async_dispatcher_send(self.hass, self.signal)
        if replayed and event["state"] == "ringing":
            self.pending_rings[call_id] = event
        else:
            self.pending_rings.pop(call_id, None)
            self.queue_delivery(event)
        return True

    def emit_call(self, event, replayed):
        payload = {key: value for key, value in event.items() if key != "caller"}
        payload["replayed"] = replayed
        self.hass.bus.async_fire(f"{DOMAIN}_call", payload)
        async_dispatcher_send(self.hass, self.call_signal, payload)

    def finish_replay(self):
        pending, self.pending_rings = self.pending_rings, {}
        for event in self.live_calls():
            if event["state"] == "ringing" and event["call_id"] in pending:
                self.emit_call(event, True)
                self.queue_delivery(event)

    def queue_delivery(self, event):
        if len(self.notification_tasks) < MAX_CALLS:
            task = self.entry.async_create_background_task(self.hass, self.deliver(event), "Simson call notification")
            self.notification_tasks.add(task)
            task.add_done_callback(self.notification_tasks.discard)

    async def deliver(self, event):
        if event["state"] == "ringing":
            # Allow replayed terminal updates to settle before notifying.
            await sleep(.5)
        call_id = event["call_id"]
        lock = self.delivery_locks.setdefault(call_id, Lock())
        try:
            async with lock:
                await self.notify(event)
        except HomeAssistantError:
            self.report_notification(event, "delivery_failed")
        finally:
            if event["state"] != "ringing":
                self.delivery_locks.pop(call_id, None)

    def report_notification(self, event, status):
        payload = {key: event[key] for key in ("call_id", "endpoint_id", "extension", "revision")}
        payload.update(site_id=self.site_id, status=status)
        self.hass.bus.async_fire(f"{DOMAIN}_notification", payload)
        async_dispatcher_send(self.hass, self.notification_signal, payload)

    async def notify(self, event):
        call_id = event["call_id"]
        tag = f"{DOMAIN}_{call_id}"
        if event["state"] != "ringing":
            delivered = self.deliveries.pop(call_id, None)
            if not delivered:
                return
            user_id, device_ids = delivered
            current = companion_devices(self.hass).get(user_id, {})
            targets = [current[device][1] for device in device_ids if device in current]
            if targets:
                await self.hass.services.async_call("notify", "mobile_app", {
                    "target": targets, "message": "clear_notification", "data": {"tag": tag},
                }, blocking=True)
                self.report_notification(event, "clear_requested")
            return
        route = self.routes.get(event["endpoint_id"])
        if not self.notifications_enabled or not route or route.get("extension") != event["extension"] or call_id in self.deliveries or route["user_id"] not in await active_users(self.hass):
            return
        # An answer/end can arrive while looking up the user.
        current = self.calls.get(call_id)
        if not self.notifications_enabled or not current or current[0]["state"] != "ringing" or current[1] <= monotonic() or self.routes.get(event["endpoint_id"]) != route:
            return
        devices = companion_devices(self.hass).get(route["user_id"], {})
        configured_devices = route["devices"]
        selected = tuple(device for device in configured_devices if device in devices) if configured_devices else tuple(devices)[:16]
        if not selected:
            return
        self.deliveries[call_id] = (route["user_id"], selected)
        query = urlencode({"simson_site": self.site_id, "simson_extension": event["extension"], "simson_call": call_id})
        path = f'{route["dashboard_path"]}?{query}'
        await self.hass.services.async_call("notify", "mobile_app", {
            "target": [devices[device][1] for device in selected],
            "title": "Incoming Simson call", "message": event["caller"],
            "data": {
                "tag": tag, "url": path, "clickAction": path, "ttl": 0, "priority": "high",
                "actions": [{"action": "URI", "title": "Open call", "uri": path}],
            },
        }, blocking=True)
        self.report_notification(event, "requested")
