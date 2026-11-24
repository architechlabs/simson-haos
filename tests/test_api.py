
import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from conftest import pure

api = pure("api")

TENANT = "11111111-1111-4111-8111-111111111111"
SITE = "22222222-2222-4222-8222-222222222222"
ENDPOINT = "33333333-3333-4333-8333-333333333333"


class Recorder:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.payload = {"ok": True}


@pytest.fixture
async def server():
    recorder = Recorder()

    async def handler(request: web.Request):
        recorder.requests.append({"method": request.method, "path": request.path, "auth": request.headers.get("Authorization"),
                                  "key": request.headers.get("Idempotency-Key"), "body": await request.json() if request.can_read_body else None})
        if recorder.status == 204:
            return web.Response(status=204)
        return web.json_response(recorder.payload, status=recorder.status)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    test_server = TestServer(app)
    await test_server.start_server()
    yield recorder, test_server
    await test_server.close()


async def make(test_server, token="simson_at_test"):
    session = aiohttp.ClientSession()

    async def provider():
        return token

    return api.SimsonApi(session, str(test_server.make_url("")), provider), session


async def test_reads_use_the_bearer_token_and_the_integration_prefix(server):
    recorder, test_server = server
    client, session = await make(test_server)
    try:
        recorder.payload = {"items": [{"id": SITE}]}
        assert await client.sites(TENANT) == [{"id": SITE}]
        request = recorder.requests[-1]
        assert request["path"] == f"/integration/v1/tenants/{TENANT}/sites"
        assert request["auth"] == "Bearer simson_at_test"
        assert request["key"] is None
    finally:
        await session.close()


async def test_writes_carry_a_unique_idempotency_key_unless_one_is_given(server):
    recorder, test_server = server
    client, session = await make(test_server)
    try:
        recorder.payload = {"id": ENDPOINT, "revision": 1}
        await client.start_call(TENANT, SITE, "n", "s", "t")
        await client.start_call(TENANT, SITE, "n", "s", "t")
        first, second = recorder.requests[-2:]
        assert first["key"] and second["key"] and first["key"] != second["key"]
        assert first["body"] == {"site_id": SITE, "media_node_id": "n", "source_endpoint_id": "s", "target_endpoint_id": "t", "timeout_sec": 30}
        await client.start_call(TENANT, SITE, "n", "s", "t", key="fixed-key")
        assert recorder.requests[-1]["key"] == "fixed-key"
    finally:
        await session.close()


@pytest.mark.parametrize("status,error", [
    (401, "SimsonAuthError"), (402, "SimsonPlanError"), (403, "SimsonPermissionError"), (404, "SimsonNotFound"),
    (409, "SimsonConflict"), (429, "SimsonRateLimited"), (500, "SimsonConnectionError"), (503, "SimsonConnectionError"), (400, "SimsonApiError"),
])
async def test_status_codes_map_to_specific_errors(server, status, error):
    recorder, test_server = server
    client, session = await make(test_server)
    try:
        recorder.status = status
        with pytest.raises(getattr(api, error)):
            await client.me()
    finally:
        await session.close()


async def test_unreachable_server_is_a_connection_error():
    session = aiohttp.ClientSession()

    async def provider():
        return "simson_at_test"

    try:
        client = api.SimsonApi(session, "http://127.0.0.1:1", provider)
        with pytest.raises(api.SimsonConnectionError):
            await client.me()
    finally:
        await session.close()


async def test_redirects_are_not_followed(server):
    recorder, test_server = server
    client, session = await make(test_server)
    try:
        recorder.status = 302
        with pytest.raises(api.SimsonApiError):
            await client.me()
    finally:
        await session.close()


async def test_start_call_and_hang_up_use_the_call_routes(server):
    recorder, test_server = server
    client, session = await make(test_server)
    try:
        await client.start_call(TENANT, SITE, "node", "src", "dst", timeout=20, video=True)
        post = recorder.requests[-1]
        assert post["path"] == f"/integration/v1/tenants/{TENANT}/call-intents"
        assert post["body"] == {"site_id": SITE, "media_node_id": "node", "source_endpoint_id": "src", "target_endpoint_id": "dst", "timeout_sec": 20, "video": True}
        await client.hang_up(TENANT, SITE, "call1", 4)
        assert recorder.requests[-1]["path"].endswith("/sites/%s/calls/call1/disconnect" % SITE)
        assert recorder.requests[-1]["body"] == {"expected_revision": 4}
        await client.cancel_call(TENANT, "call1", 2)
        assert recorder.requests[-1]["path"].endswith("/call-intents/call1/cancel")
    finally:
        await session.close()
