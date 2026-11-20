from datetime import timezone

from conftest import pure

model = pure("model")


def ext(identifier, online, **kw):
    values = dict(id=identifier, name=identifier, extension=identifier, node_id="n", enabled=True, revision=1, credential_revision=0, gateway=False, online=online)
    values.update(kw)
    return model.Extension(**values)


def test_presence_changes_report_only_definite_flips():
    before = {"a": ext("a", True), "b": ext("b", False), "c": ext("c", None), "gone": ext("gone", True)}
    after = {"a": ext("a", False), "b": ext("b", True), "c": ext("c", True), "new": ext("new", True)}
    changes = {(e.id, kind) for e, kind in model.diff_presence(before, after)}
    assert changes == {("a", "offline"), ("b", "online"), ("new", "added"), ("gone", "removed")}


def test_losing_sight_of_the_voice_service_is_not_an_offline_alarm():
    before = {"a": ext("a", True)}
    after = {"a": ext("a", None)}
    assert model.diff_presence(before, after) == []
    assert model.diff_presence(None, after) == []
    assert model.diff_presence(before, before) == []


def test_extensions_carry_codecs_and_last_seen():
    snapshot = {"endpoints": [{"id": "e1", "display_name": "Kitchen", "extension": "1201", "desired_enabled": True, "codecs": ["OPUS", "PCMU"]}]}
    presence = {"endpoints": [{"endpoint_id": "e1", "state": "online", "observed_at": "2026-11-20T12:00:00Z"}]}
    built = model.build_extensions(snapshot, presence)["e1"]
    assert built.codecs == ("OPUS", "PCMU") and built.observed_at == "2026-11-20T12:00:00Z"
    default = model.build_extensions({"endpoints": [{"id": "e2", "extension": "1202"}]}, {})["e2"]
    assert default.codecs == ("PCMU", "PCMA") and default.observed_at is None


def test_automations_are_flattened_across_nodes():
    first = {"items": [{"id": "a1", "node_id": "n1", "revision": 3, "settings": {"display_name": "Front door", "enabled": True, "source_endpoint_id": "s", "target_endpoint_id": "t", "cooldown_sec": 20, "video": True}}]}
    second = {"items": [{"id": "a2", "node_id": "n2", "revision": 1, "settings": {"display_name": "Gate", "enabled": False, "source_endpoint_id": "s2", "target_endpoint_id": "t2", "cooldown_sec": 90}}]}
    parsed = model.parse_automations([first, second, {}])
    assert set(parsed) == {"a1", "a2"}
    assert parsed["a1"].name == "Front door" and parsed["a1"].video and parsed["a1"].revision == 3 and parsed["a1"].cooldown == 20
    assert parsed["a2"].enabled is False and parsed["a2"].video is False


def test_numbers_and_summary():
    numbers = model.parse_numbers([{"id": "1", "number": "+23057000001", "source": "assigned"}])
    assert numbers[0].number == "+23057000001"
    summary = model.parse_summary({"summary": {"window_days": 30, "calls": 25, "answered_calls": 20, "unanswered_calls": 5, "active_sessions": 1, "connected_seconds": 750}})
    assert (summary.calls, summary.answered, summary.unanswered, summary.connected_seconds) == (25, 20, 5, 750)
    assert model.parse_summary({}) == model.Summary()


def test_history_rows_are_newest_first_and_bounded():
    calls = {f"c{i}": model.CallInfo(f"c{i}", "ended", 1, f"2026-11-20T12:0{i}:00Z", f"2026-11-20T12:0{i}:05Z" if i % 2 == 0 else None, None, i) for i in range(6)}
    rows = model.history_rows(calls, 3)
    assert [row["call_id"] for row in rows] == ["c5", "c4", "c3"]
    assert rows[1]["answered"] is True and rows[0]["answered"] is False and rows[1]["duration_seconds"] == 4
    assert len(model.history_rows(calls, 1000)) == 6
    assert len(model.history_rows(calls, 0)) == 1


def test_last_call_time_and_timestamps():
    calls = {"a": model.CallInfo("a", "ended", 1, "2026-11-20T10:00:00Z", None, None, 0), "b": model.CallInfo("b", "ended", 1, "2026-11-20T11:00:00Z", None, None, 0)}
    assert model.last_call_time(calls) == "2026-11-20T11:00:00Z"
    assert model.last_call_time({}) is None
    parsed = model.parse_timestamp("2026-11-20T11:00:00")
    assert parsed.tzinfo == timezone.utc
    assert model.parse_timestamp("garbage") is None and model.parse_timestamp(None) is None
