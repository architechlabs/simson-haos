"""Exercise a saved Simson location's first refresh in Home Assistant Core."""

import asyncio
from importlib import import_module
import json
from time import time
from types import MappingProxyType

import pytest


async def test_saved_location_loads_and_dispatches_call_and_refresh_listeners(tmp_path, monkeypatch):
    pytest.importorskip("homeassistant")
    from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant, callback

    from custom_components import simson
    from custom_components.simson.const import BUS_EVENT, DOMAIN
    from custom_components.simson.sse import SseMessage

    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    await simson.async_register_services(hass)
    obsolete = ("create_extension", "reset_extension_password", "delete_extension", "set_extension_enabled")
    assert not any(hass.services.has_service(DOMAIN, service) for service in obsolete)
    assert hass.services.has_service(DOMAIN, "call")
    assert hass.services.has_service(DOMAIN, "get_targets")
    entry = ConfigEntry(
        domain=DOMAIN,
        title="Fixture workspace · office",
        version=1,
        minor_version=1,
        data={
            "auth_implementation": DOMAIN,
            "token": {"access_token": "fixture-token", "expires_at": time() + 3600},
            "tenant_id": "fixture-workspace",
            "site_id": "fixture-office",
        },
        options={},
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
        unique_id="fixture-workspace:fixture-office",
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )

    stream_connected = asyncio.Event()
    send_call = asyncio.Event()
    call_received = asyncio.Event()
    data_refreshed = asyncio.Event()
    entities = {}

    class FixtureApi:
        def __init__(self, session, url, token):
            self.token = token

        async def snapshot(self, tenant, site):
            assert (tenant, site) == ("fixture-workspace", "fixture-office")
            assert await self.token() == "fixture-token"
            return {"endpoints": [{"id": "fixture-phone", "extension": "1201", "display_name": "Desk"}]}

        async def presence(self, tenant, site):
            return {"state": "fresh", "endpoints": [{"endpoint_id": "fixture-phone", "state": "online"}]}

        async def call_dashboard(self, tenant):
            return {"calls": {"items": []}}

        async def numbers(self, tenant, site):
            return []

        async def events(self, tenant, last_event_id):
            yield SseMessage("ready", "1", "{}")
            stream_connected.set()
            await send_call.wait()
            event = {"seq": 2, "kind": "ringing", "call_id": "fixture-call", "revision": 1}
            yield SseMessage("call", "2", json.dumps(event))
            await asyncio.Event().wait()

    async def forward_platforms(config_entries, config_entry, platforms):
        for platform in platforms:
            module = import_module(f"custom_components.simson.{platform}")
            await module.async_setup_entry(hass, config_entry, entities.setdefault(platform, []).extend)

    monkeypatch.setattr(simson, "SimsonApi", FixtureApi)
    monkeypatch.setattr(simson, "async_get_clientsession", lambda hass: None)
    monkeypatch.setattr(ConfigEntries, "async_forward_entry_setups", forward_platforms)
    assert await simson.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data.coordinator
    try:
        assert set(entities) == set(simson.PLATFORMS)
        phone = next(entity for entity in entities["binary_sensor"] if entity.unique_id == "fixture-phone_online")
        assert phone.is_on is True
        assert len(entities["event"]) == 1
        await asyncio.wait_for(stream_connected.wait(), timeout=3)
        assert coordinator.live

        calls = []
        bus_events = []

        @callback
        def on_bus_event(event):
            bus_events.append(event.data)
            call_received.set()

        remove_bus_listener = hass.bus.async_listen(BUS_EVENT, on_bus_event)
        remove_call_listener = coordinator.async_add_call_listener(calls.append)
        remove_data_listener = coordinator.async_add_listener(data_refreshed.set)
        try:
            send_call.set()
            await asyncio.wait_for(call_received.wait(), timeout=3)
            await asyncio.wait_for(data_refreshed.wait(), timeout=3)
            assert [(event.kind, event.call.id) for event in calls] == [("incoming", "fixture-call")]
            assert [event["site_id"] for event in bus_events] == ["fixture-office"]
        finally:
            remove_data_listener()
            remove_call_listener()
            remove_bus_listener()
    finally:
        await coordinator.streamer.stop()
        await coordinator.async_shutdown()
