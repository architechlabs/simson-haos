import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from conftest import pure

api = pure("api")
model = pure("model")
resolve = pure("resolve")

TENANT = "11111111-1111-4111-8111-111111111111"
SITE = "22222222-2222-4222-8222-222222222222"
NODE = "33333333-3333-4333-8333-333333333333"


def ext(identifier, number, **kw):
    values = dict(id=identifier, name=f"Phone {number}", extension=number, node_id="n", enabled=True, revision=1, credential_revision=0, gateway=False, online=True)
    values.update(kw)
    return model.Extension(**values)


def auto(identifier, name, enabled=True):
    return model.Automation(id=identifier, name=name, node_id=NODE, source_id="s", target_id="t", enabled=enabled, revision=4, cooldown=20, video=False)


def test_default_caller_prefers_the_choice_then_the_first_usable_phone():
    ws = model.Workspace(extensions={e.id: e for e in (ext("g", "1701", gateway=True), ext("b", "1202"), ext("a", "1201"), ext("c", "1203", enabled=False))})
    assert resolve.default_caller(ws, "1202") == "1202"
    assert resolve.default_caller(ws, None) == "1201"
    assert resolve.default_caller(ws, "1203") == "1201", "a switched-off phone is not a valid default"
    assert resolve.default_caller(ws, "1701") == "1201", "a gateway is not a valid default"
    with pytest.raises(resolve.ResolveError):
        resolve.default_caller(model.Workspace(), None)


def test_presets_are_found_by_id_or_name_and_must_be_on():
    ws = model.Workspace(automations={"a1": auto("a1", "Front door"), "a2": auto("a2", "Gate", enabled=False), "a3": auto("a3", "front DOOR 2")})
    assert resolve.find_automation(ws, "a1").name == "Front door"
    assert resolve.find_automation(ws, "gate").id == "a2"
    with pytest.raises(resolve.ResolveError, match="no call preset"):
        resolve.find_automation(ws, "Back door")
    with pytest.raises(resolve.ResolveError, match="turned off"):
        resolve.runnable(resolve.find_automation(ws, "Gate"))
    twin = model.Workspace(automations={"x": auto("x", "Bell"), "y": auto("y", "bell")})
    with pytest.raises(resolve.ResolveError, match="More than one"):
        resolve.find_automation(twin, "BELL")


@pytest.fixture
async def server():
    seen = []

    async def handler(request: web.Request):
        seen.append({"method": request.method, "path_qs": request.path_qs, "key": request.headers.get("Idempotency-Key"), "body": await request.json() if request.can_read_body else None})
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    test_server = TestServer(app)
    await test_server.start_server()
    yield seen, test_server
    await test_server.close()


async def client_for(test_server):
    session = aiohttp.ClientSession()

    async def provider():
        return "simson_at_x"

    return api.SimsonApi(session, str(test_server.make_url("")), provider), session


async def test_history_query_is_built_only_from_given_arguments(server):
    seen, test_server = server
    client, session = await client_for(test_server)
    try:
        await client.call_dashboard(TENANT)
        await client.call_dashboard(TENANT, limit=50)
        await client.call_dashboard(TENANT, after="abc", limit=10)
        assert [item["path_qs"] for item in seen] == [
            f"/integration/v1/tenants/{TENANT}/call-dashboard",
            f"/integration/v1/tenants/{TENANT}/call-dashboard?limit=50",
            f"/integration/v1/tenants/{TENANT}/call-dashboard?after=abc&limit=10",
        ]
    finally:
        await session.close()


async def test_running_a_preset_sends_a_fresh_event_and_uses_it_as_the_retry_key(server):
    seen, test_server = server
    client, session = await client_for(test_server)
    try:
        await client.run_automation(TENANT, SITE, NODE, "auto-1", 4)
        await client.run_automation(TENANT, SITE, NODE, "auto-1", 4)
        first, second = seen
        assert first["path_qs"] == f"/integration/v1/tenants/{TENANT}/sites/{SITE}/nodes/{NODE}/automations/auto-1/trigger"
        assert first["body"]["expected_revision"] == 4 and first["body"]["occurred_at"].endswith("Z")
        assert first["key"] == first["body"]["event_id"] and first["key"] != second["key"]
        await client.automations(TENANT, SITE, NODE)
        assert seen[-1]["method"] == "GET" and seen[-1]["path_qs"].endswith("/automations")
    finally:
        await session.close()
