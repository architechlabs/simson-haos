from datetime import datetime, timedelta, timezone

from conftest import pure

model = pure("model")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def test_browser_outbound_directory_preserves_source_entitlements():
    extensions = {
        "browser": model.Extension("browser", "Screen", "100", "office", True, 1, 1, False, True),
        "desk": model.Extension("desk", "Desk", "1002", "lobby", True, 1, 1, False, True),
        "trunk": model.Extension("trunk", "WhatsApp", "1190", "office", True, 1, 1, True, True),
    }
    snapshot = {"nodes": [{"id": "office"}, {"id": "lobby"}], "gateway_route_sets": [{"node_id": "office", "routes": [
        {"id": "whatsapp", "enabled": True, "gateway_endpoint_id": "trunk",
         "outbound": {"access_prefix": "*833", "source_ids": ["browser", "trunk"]}},
        {"id": "disabled", "enabled": False, "gateway_endpoint_id": "trunk",
         "outbound": {"access_prefix": "*834", "source_ids": ["desk"]}},
    ]}], "route_sets": [{"node_id": "lobby", "routes": [{"code": "*869250"}]}]}
    numbers = model.parse_numbers([
        {"id": "airtel", "number": "+911244699250", "airtel": {"gateway_configured": True, "access_code": "*869250"}},
        {"id": "unused", "number": "+911244699251", "airtel": {"gateway_configured": False, "access_code": "*869251"}},
    ])
    assert model.outbound_routes(snapshot, extensions, numbers) == [
        {"id": "airtel", "name": "Airtel · 9250", "prefix": "*869250", "extensions": ["100"]},
        {"id": "whatsapp", "name": "WhatsApp", "prefix": "*833", "extensions": ["100"]},
    ]


def call(call_id="c1", phase="ringing", connected=None, ended=None, seconds=0, started=None):
    return model.CallInfo(call_id, phase, 1, started or NOW.isoformat(), connected, ended, seconds)


def kinds(events):
    return [event.kind for event in events]


def test_first_snapshot_is_a_silent_baseline():
    assert model.diff_calls(None, {"c1": call()}, NOW) == []


def test_a_new_ringing_call_is_incoming_once():
    first = {}
    after = {"c1": call()}
    assert kinds(model.diff_calls(first, after, NOW)) == ["incoming"]
    assert model.diff_calls(after, after, NOW) == []


def test_ringing_then_active_then_ended_is_answered_then_ended():
    ringing = {"c1": call()}
    active = {"c1": call(phase="active", connected=NOW.isoformat())}
    ended = {"c1": call(phase="ended", connected=NOW.isoformat(), ended=NOW.isoformat(), seconds=42)}
    assert kinds(model.diff_calls(ringing, active, NOW)) == ["answered"]
    events = model.diff_calls(active, ended, NOW)
    assert kinds(events) == ["ended"] and events[0].call.connected_seconds == 42


def test_ringing_then_ended_without_connecting_is_missed():
    ringing = {"c1": call()}
    ended = {"c1": call(phase="ended", ended=NOW.isoformat())}
    assert kinds(model.diff_calls(ringing, ended, NOW)) == ["missed"]


def test_a_call_first_seen_active_reports_incoming_and_answered():
    assert kinds(model.diff_calls({}, {"c1": call(phase="active", connected=NOW.isoformat())}, NOW)) == ["incoming", "answered"]


def test_old_history_is_not_replayed_but_a_just_ended_call_is_reported():
    old = {"c1": call(phase="ended", connected=NOW.isoformat(), ended=(NOW - timedelta(hours=3)).isoformat())}
    fresh = {"c2": call("c2", phase="ended", ended=(NOW - timedelta(seconds=30)).isoformat())}
    assert model.diff_calls({}, old, NOW) == []
    assert kinds(model.diff_calls({}, fresh, NOW)) == ["missed"]


def test_multiple_calls_are_tracked_independently():
    before = {"a": call("a"), "b": call("b", phase="active", connected=NOW.isoformat())}
    after = {"a": call("a", phase="active", connected=NOW.isoformat()), "b": call("b", phase="ended", connected=NOW.isoformat(), ended=NOW.isoformat())}
    assert sorted((event.call.id, event.kind) for event in model.diff_calls(before, after, NOW)) == [("a", "answered"), ("b", "ended")]


def test_extensions_combine_snapshot_and_presence():
    snapshot = {"endpoints": [
        {"id": "e1", "display_name": "Kitchen", "extension": "1201", "node_id": "n1", "desired_enabled": True, "revision": 3},
        {"id": "e2", "display_name": "Hall", "extension": "1202", "node_id": "n1", "desired_enabled": True, "revision": 1},
        {"id": "e3", "display_name": "Old", "extension": "1203", "retired": True},
        {"id": "g1", "display_name": "SIM gateway", "extension": "1701", "gateway": True, "desired_enabled": True},
    ]}
    presence = {"endpoints": [{"endpoint_id": "e1", "state": "online"}, {"endpoint_id": "e2", "state": "offline"}]}
    result = model.build_extensions(snapshot, presence)
    assert set(result) == {"e1", "e2", "g1"}
    assert result["e1"].online is True and result["e2"].online is False and result["g1"].online is None
    assert result["g1"].gateway and result["e1"].revision == 3


def test_polling_speeds_up_only_while_calls_are_live():
    quiet = model.Workspace()
    assert model.interval_for(quiet, 30, 4) == 30
    quiet.calls = {"c": call(phase="ended", ended=NOW.isoformat())}
    assert model.interval_for(quiet, 30, 4) == 30
    quiet.calls = {"c": call(phase="ringing")}
    assert model.interval_for(quiet, 30, 4) == 4
    assert model.interval_for(model.Workspace(active_calls=1), 30, 4) == 4


def test_parse_calls_reads_the_dashboard_shape():
    dashboard = {"summary": {}, "calls": {"items": [{"id": "x", "phase": "active", "revision": 2, "started_at": "t", "connected_at": "t", "ended_at": None, "connected_seconds": 7}], "next_after": None}}
    parsed = model.parse_calls(dashboard)
    assert parsed["x"].phase == "active" and parsed["x"].connected_seconds == 7 and parsed["x"].revision == 2
    assert model.parse_calls({}) == {}


def test_runtime_prefers_an_applied_enabled_node_and_exposes_sip_details():
    presence = {"media_runtimes": [
        {"id": "n-off", "enabled": False, "configuration_state": "applied"},
        {"id": "n-pending", "enabled": True, "configuration_state": "pending"},
        {"id": "n-ok", "enabled": True, "configuration_state": "applied", "sip_connection": {"server": "sip.example", "port": 5061, "transport": "tls", "realm": "r"}},
    ]}
    node, sip = model.parse_runtime(presence)
    assert node == "n-ok" and sip["port"] == 5061
    assert model.parse_runtime({}) == (None, None)
    assert model.parse_runtime({"media_runtimes": [{"id": "x", "enabled": False}]}) == (None, None)
