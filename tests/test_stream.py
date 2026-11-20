import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from conftest import pure

api = pure("api")
sse = pure("sse")
model = pure("model")

TENANT = "11111111-1111-4111-8111-111111111111"


async def chunks(*parts: bytes):
    for part in parts:
        yield part


async def collect(*parts: bytes):
    return [message async for message in sse.parse_sse(chunks(*parts))]


async def test_parses_blocks_comments_and_ids_split_across_chunks():
    got = await collect(b": keep-alive\n\nretry: 3000\nid: 5\nevent: ready\ndata: {\"seq\":5}\n\n", b"id: 6\nevent: ca", b"ll\ndata: {\"a\":1}\r\ndata: 2\r\n\r\n")
    assert [(m.event, m.id, m.data) for m in got] == [("ready", "5", '{"seq":5}'), ("call", "6", '{"a":1}\n2')]
    assert got[0].retry == 3000


async def test_blocks_without_data_are_not_messages():
    assert await collect(b"id: 9\n\n: hi\n\n") == []


async def test_default_event_name_and_leading_space_rules():
    got = await collect(b"data:no-space\n\ndata:  two\n\n")
    assert [(m.event, m.data) for m in got] == [("message", "no-space"), ("message", " two")]


async def test_rejects_oversized_messages_and_lines():
    with pytest.raises(sse.SseError):
        await collect(b"data: " + b"x" * 40000 + b"\ndata: " + b"y" * 40000 + b"\n\n")
    with pytest.raises(sse.SseError):
        await collect(b"x" * 80000)


def test_backoff_grows_then_caps():
    values = [sse.backoff_seconds(n, jitter=0) for n in range(10)]
    assert values[:4] == [1, 2, 4, 8]
    assert max(values) == 60
    assert sse.backoff_seconds(3, jitter=1) == 10


def test_live_events_map_to_call_events():
    event = model.parse_live_event({"seq": 7, "kind": "ringing", "call_id": "c1", "revision": 2, "occurred_at": "2026-11-20T10:00:00Z",
                                    "from": {"id": "e1", "extension": "1201", "name": "Kitchen"}, "to": {"id": "e2", "extension": "1202", "name": "Hall"}})
    assert (event.kind, event.seq, event.call.phase, event.call.started_at) == ("incoming", 7, "ringing", "2026-11-20T10:00:00Z")
    assert event.caller == {"extension": "1201", "name": "Kitchen"} and event.callee == {"extension": "1202", "name": "Hall"}
    answered = model.parse_live_event({"seq": 8, "kind": "answered", "call_id": "c1", "occurred_at": "2026-11-20T10:00:05Z", "from": None, "to": None})
    assert (answered.kind, answered.call.phase, answered.call.connected_at, answered.caller) == ("answered", "active", "2026-11-20T10:00:05Z", None)
    assert model.parse_live_event({"seq": 9, "kind": "missed", "call_id": "c1"}).call.phase == "ended"


@pytest.mark.parametrize("bad", [None, [], {"seq": 1, "kind": "requested", "call_id": "c"}, {"seq": True, "kind": "ended", "call_id": "c"}, {"seq": 1, "kind": "ended"}, {"seq": "1", "kind": "ended", "call_id": "c"}])
def test_unusable_live_events_are_ignored(bad):
    assert model.parse_live_event(bad) is None


@pytest.fixture
async def stream_server():
    state = {"status": 200, "seen": [], "body": b"retry: 3000\nid: 1\nevent: ready\ndata: {\"seq\":1}\n\nid: 2\nevent: call\ndata: {\"seq\":2}\n\n"}

    async def handler(request: web.Request):
        state["seen"].append({"path": request.path, "auth": request.headers.get("Authorization"), "last": request.headers.get("Last-Event-ID"), "accept": request.headers.get("Accept")})
        if state["status"] != 200:
            return web.json_response({"code": "x"}, status=state["status"])
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(state["body"])
        return response

    app = web.Application()
    app.router.add_get("/integration/v1/tenants/{tenant}/events", handler)
    server = TestServer(app)
    await server.start_server()
    async with aiohttp.ClientSession() as session:
        async def token():
            return "tok"
        yield state, api.SimsonApi(session, str(server.make_url("")), token)
    await server.close()


async def test_events_streams_messages_and_sends_resume_header(stream_server):
    state, client = stream_server
    got = [m async for m in client.events(TENANT, "41")]
    assert [m.event for m in got] == ["ready", "call"]
    assert state["seen"] == [{"path": f"/integration/v1/tenants/{TENANT}/events", "auth": "Bearer tok", "last": "41", "accept": "text/event-stream"}]
    [m async for m in client.events(TENANT)]
    assert state["seen"][1]["last"] is None


@pytest.mark.parametrize("status,error", [(401, "SimsonAuthError"), (403, "SimsonPermissionError"), (404, "SimsonNotFound"), (429, "SimsonRateLimited"), (503, "SimsonConnectionError")])
async def test_events_maps_failures(stream_server, status, error):
    state, client = stream_server
    state["status"] = status
    with pytest.raises(getattr(api, error)):
        async for _ in client.events(TENANT):
            pass


async def test_events_reports_a_broken_stream_as_a_connection_error(stream_server):
    state, client = stream_server
    state["body"] = b"data: " + b"x" * 80000 + b"\n"
    with pytest.raises(api.SimsonConnectionError):
        async for _ in client.events(TENANT):
            pass
