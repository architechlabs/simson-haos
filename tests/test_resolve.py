import pytest

from conftest import pure

model = pure("model")
resolve = pure("resolve")


def workspace(node="node-1"):
    def ext(identifier, number, **kw):
        values = dict(id=identifier, name=f"Phone {number}", extension=number, node_id="n", enabled=True, revision=1, credential_revision=0, gateway=False, online=True)
        values.update(kw)
        return model.Extension(**values)

    return model.Workspace(
        media_node_id=node,
        sip={"server": "sip.example", "port": 5061, "transport": "tls", "realm": "r.example"},
        extensions={e.id: e for e in (ext("a", "1201"), ext("b", "1202"), ext("c", "1203", enabled=False), ext("g", "1701", gateway=True))},
    )


def test_finds_extensions_by_number_and_rejects_bad_input():
    ws = workspace()
    assert resolve.find_extension(ws, "1201").id == "a"
    assert resolve.find_extension(ws, 1202).id == "b"
    for bad in ("", "abc", "0120", "12 01", "99999999999", "1201;drop"):
        with pytest.raises(resolve.ResolveError):
            resolve.find_extension(ws, bad)
    with pytest.raises(resolve.ResolveError):
        resolve.find_extension(ws, "9999")


def test_plans_a_phone_to_phone_call():
    assert resolve.plan_call(workspace(), "1201", "1202") == ("node-1", "a", "b")


@pytest.mark.parametrize("source,target,message", [
    ("1201", "1201", "itself"),
    ("1201", "1203", "turned off"),
    ("1203", "1201", "turned off"),
    ("1201", "1701", "gateway"),
    ("1701", "1201", "gateway"),
])
def test_refuses_impossible_calls_with_a_readable_reason(source, target, message):
    with pytest.raises(resolve.ResolveError, match=message):
        resolve.plan_call(workspace(), source, target)


def test_refuses_calls_when_no_voice_service_is_active():
    with pytest.raises(resolve.ResolveError, match="voice service"):
        resolve.plan_call(workspace(node=None), "1201", "1202")


def test_call_button_chooses_another_phone_if_the_default_is_its_target():
    ws = workspace()
    assert resolve.default_caller(ws, "1201", exclude_id="a") == "1202"
    assert resolve.plan_call(ws, resolve.default_caller(ws, "1201", exclude_id="a"), "1201") == ("node-1", "b", "a")
    assert resolve.default_caller(ws, "1201", exclude_id="b") == "1201"
    del ws.extensions["b"]
    with pytest.raises(resolve.ResolveError, match="another enabled phone"):
        resolve.default_caller(ws, "1201", exclude_id="a")
