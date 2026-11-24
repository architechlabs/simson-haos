"""Local protocol and notification tests without a Home Assistant instance."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

PACKAGE = "_simson_integration_fixture"
component = Path(__file__).resolve().parents[1] / "custom_components" / "simson_v2"
package = ModuleType(PACKAGE)
package.__path__ = [str(component)]
sys.modules[PACKAGE] = package
protocol = importlib.import_module(f"{PACKAGE}.protocol")
journal = importlib.import_module(f"{PACKAGE}.journal")

SITE = "11111111-1111-4111-8111-111111111111"
TENANT = "99999999-9999-4999-8999-999999999999"
CALL = "22222222-2222-4222-8222-222222222222"
ENDPOINT = "33333333-3333-4333-8333-333333333333"
USER = "a" * 32
OTHER = "b" * 32


def event(**overrides):
    return {
        "site_id": SITE, "call_id": CALL, "endpoint_id": ENDPOINT, "revision": 1,
        "state": "ringing", "extension": "1200", "caller": "Reception",
        "occurred_at": datetime.now(timezone.utc).isoformat(), **overrides,
    }


class ProtocolTest(unittest.TestCase):
    def test_scope_age_and_payload(self):
        self.assertEqual(protocol.parse_event(event(), SITE)["endpoint_id"], ENDPOINT)
        for invalid in (
            event(site_id=CALL), event(revision=True), event(state="disconnect"),
            event(extension="+15550002222"), event(extra="unknown field"),
            event(occurred_at=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()),
        ):
            with self.assertRaises(ValueError):
                protocol.parse_event(invalid, SITE)
        for invalid in ("//outside.example", "/local?site=wrong", "/../redirect", "https://outside.example"):
            with self.assertRaises(ValueError):
                protocol.dashboard_path(invalid)

    def test_checkpoint_restores_late_cursor_ids_and_deduplicates(self):
        old = journal.Journal(TENANT, SITE)
        self.assertTrue(old.advance(100, ready=True))
        self.assertFalse(old.advance(99))
        self.assertTrue(old.advance(104))
        self.assertTrue(old.record(event()))
        state = old.data()
        self.assertNotIn("caller", state["calls"][0])
        resumed = journal.Journal(TENANT, SITE, state)
        self.assertEqual(resumed.cursor, 104)
        self.assertFalse(resumed.advance(104))
        self.assertTrue(resumed.advance(103))
        self.assertFalse(resumed.record(event()))
        self.assertEqual(resumed.totals["ringing"], 1)
        other = journal.Journal(TENANT, CALL, state)
        self.assertIsNone(other.cursor)
        self.assertEqual(other.calls, {})


class CallDeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        exceptions = ModuleType("homeassistant.exceptions")
        exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
        dispatch = ModuleType("homeassistant.helpers.dispatcher")
        dispatch.async_dispatcher_send = lambda *_: None
        companion = ModuleType(f"{PACKAGE}.companion")
        companion.companion_devices = lambda _: {
            USER: {"my-phone": ("My phone", "private-destination-one")},
            OTHER: {"other-phone": ("Other phone", "private-destination-two")},
        }

        async def active(_):
            return {USER: object(), OTHER: object()}
        companion.active_users = active
        with patch.dict(sys.modules, {
            exceptions.__name__: exceptions, dispatch.__name__: dispatch, companion.__name__: companion,
        }):
            self.runtime = importlib.import_module(f"{PACKAGE}.runtime")
        self.mobile = []
        self.emitted = []
        self.pending = []

        async def call(domain, service, data, **_):
            self.mobile.append((domain, service, data))

        def task(_hass, coro, _name):
            self.pending.append(asyncio.create_task(coro))
            return self.pending[-1]

        self.site = self.runtime.Site(
            SimpleNamespace(
                bus=SimpleNamespace(async_fire=lambda kind, value: self.emitted.append((kind, value))),
                services=SimpleNamespace(async_call=call),
                loop=asyncio.get_event_loop(),
            ),
            SimpleNamespace(
                data={"site_id": SITE, "tenant_id": TENANT},
                options={"routes": {ENDPOINT: {
                    "user_id": USER, "devices": ["my-phone", "other-phone"], "dashboard_path": "/lovelace/calls",
                }}},
                async_create_background_task=task,
            ),
        )
        self.addCleanup(self.site.stop_expiry)

    async def settle(self):
        await asyncio.gather(*self.pending)
        self.pending.clear()

    async def test_only_owned_selected_device_and_clear(self):
        normal = protocol.parse_event(event(), SITE)
        self.assertTrue(await self.site.ingest(normal))
        self.assertFalse(await self.site.ingest(normal))
        await self.settle()
        self.assertEqual(len(self.mobile), 1)
        body = self.mobile[0][2]
        self.assertEqual(body["target"], ["private-destination-one"])
        self.assertIn("/lovelace/calls?", body["data"]["url"])
        self.assertNotIn("caller", self.emitted[0][1])
        self.assertEqual(self.emitted[1][1]["status"], "requested")
        self.assertNotIn("private-destination-one", repr(self.emitted))
        self.assertTrue(await self.site.ingest(protocol.parse_event(event(state="answered", revision=2), SITE)))
        await self.settle()
        self.assertEqual(self.mobile[-1][2]["message"], "clear_notification")

    async def test_replayed_ringing_is_suppressed_when_call_has_ended(self):
        await self.site.ingest(protocol.parse_event(event(), SITE), replayed=True)
        await self.site.ingest(protocol.parse_event(event(state="missed", revision=2), SITE), replayed=True)
        self.site.finish_replay()
        await self.settle()
        self.assertEqual(self.mobile, [])
        self.assertFalse(await self.site.ingest(protocol.parse_event(event(revision=3), SITE)))
        self.assertEqual([value["state"] for _, value in self.emitted], ["missed"])

    async def test_unanswered_ring_can_be_recovered_once_after_catchup(self):
        await self.site.ingest(protocol.parse_event(event(), SITE), replayed=True)
        self.assertEqual(self.emitted, [])
        self.site.finish_replay()
        self.site.finish_replay()
        await self.settle()
        self.assertEqual(len(self.mobile), 1)
        self.assertTrue(self.emitted[0][1]["replayed"])

    async def test_notification_switch_does_not_disable_event_automations(self):
        self.site.entry.options["notifications_enabled"] = False
        await self.site.ingest(protocol.parse_event(event(), SITE))
        await self.settle()
        self.assertEqual(self.mobile, [])
        self.assertEqual(self.emitted[0][1]["state"], "ringing")


class InventoryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        dispatch = ModuleType("homeassistant.helpers.dispatcher")
        dispatch.async_dispatcher_send = lambda *_: None
        cloud = ModuleType(f"{PACKAGE}.cloud")
        cloud.CloudUnavailable = type("CloudUnavailable", (Exception,), {})
        cloud.Reauthorize = type("Reauthorize", (Exception,), {})
        cloud.api_path = lambda tenant, site: f"/v1/tenants/{tenant}/sites/{site}"
        cloud.cloud_get = None
        with patch.dict(sys.modules, {dispatch.__name__: dispatch, cloud.__name__: cloud}):
            self.inventory = importlib.import_module(f"{PACKAGE}.inventory")
        self.catalog = {
            "site": {"id": SITE, "tenant_id": TENANT}, "nodes": [{"desired_enabled": True}],
            "endpoints": [{"id": ENDPOINT, "tenant_id": TENANT, "site_id": SITE, "display_name": "Entrance",
                           "extension": "1200", "codecs": ["PCMU", "H264"], "desired_enabled": True,
                           "provisioning_state": "unassigned", "credential_configured": True}],
        }

    def test_scopes_catalog_and_removes_sensitive_fields(self):
        self.catalog["endpoints"][0]["fixture_secret"] = "never-project"
        phones, groups = self.inventory.project_catalog(self.catalog, TENANT, SITE)
        self.assertEqual(groups, 1)
        self.assertTrue(phones[ENDPOINT].video)
        self.assertEqual(phones[ENDPOINT].configuration, "unassigned")
        self.assertNotIn("never-project", repr(phones))
        self.catalog["endpoints"][0]["site_id"] = CALL
        with self.assertRaises(ValueError):
            self.inventory.project_catalog(self.catalog, TENANT, SITE)

    async def test_stale_presence_does_not_emit_a_device_drop(self):
        async def access():
            return "fixture-access"

        async def sample(_hass, url, _access, _limit):
            if url.endswith("/snapshot"):
                return self.catalog
            quality, state = next(samples)
            if quality == "unavailable":
                raise self.inventory.CloudUnavailable
            return {"state": quality, "endpoints": [{"endpoint_id": ENDPOINT, "state": state}],
                    "total_nodes": 1, "expected_nodes": 1, "fresh_nodes": 1}

        events = []
        samples = iter([("fresh", "online"), ("unavailable", "offline"), ("fresh", "online"), ("fresh", "offline")])
        site = SimpleNamespace(
            entry=SimpleNamespace(data={"tenant_id": TENANT}), site_id=SITE, inventory=None,
            hass=SimpleNamespace(bus=SimpleNamespace(async_fire=lambda name, payload: events.append((name, payload)))),
            inventory_signal="inventory", registration_signal="registration",
        )
        feed = self.inventory.InventoryFeed(site, SimpleNamespace(access=access))
        with patch.object(self.inventory, "cloud_get", sample):
            await feed.sample()
            last_check = site.inventory_updated_at
            await feed.sample()
            self.assertEqual(site.inventory_state, "unavailable")
            self.assertEqual(site.inventory_updated_at, last_check)
            self.assertEqual(events, [])
            await feed.sample()
            await feed.sample()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["previous_state"], "online")
        self.assertEqual(events[0][1]["state"], "offline")


if __name__ == "__main__":
    unittest.main()
