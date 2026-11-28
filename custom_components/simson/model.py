"""Plain data model and event detection (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

PHASES_RINGING = ("requesting", "ringing")


@dataclass(frozen=True)
class Extension:
    id: str
    name: str
    extension: str
    node_id: str | None
    enabled: bool
    revision: int
    credential_revision: int
    gateway: bool
    online: bool | None  # None when presence is not observed
    codecs: tuple[str, ...] = ("PCMU", "PCMA")
    observed_at: str | None = None  # when presence last saw it
    registration_realm: str | None = None


@dataclass(frozen=True)
class Automation:
    """A saved call preset, such as a doorbell flow that rings a phone."""

    id: str
    name: str
    node_id: str
    source_id: str
    target_id: str
    enabled: bool
    revision: int
    cooldown: int
    video: bool


@dataclass(frozen=True)
class CarrierNumber:
    id: str
    number: str
    source: str
    airtel_access_code: str | None = None


@dataclass(frozen=True)
class CallInfo:
    id: str
    phase: str
    revision: int
    started_at: str | None
    connected_at: str | None
    ended_at: str | None
    connected_seconds: int


@dataclass(frozen=True)
class CallEvent:
    kind: str  # incoming | answered | ended | missed
    call: CallInfo
    caller: dict[str, str] | None = None  # {"extension", "name"} when the call started in Simson
    callee: dict[str, str] | None = None
    seq: int | None = None  # position in the live stream, None when found by polling


@dataclass(frozen=True)
class Summary:
    window_days: int = 0
    calls: int = 0
    answered: int = 0
    unanswered: int = 0
    active_sessions: int = 0
    connected_seconds: int = 0


@dataclass
class Workspace:
    nodes: dict[str, str] = field(default_factory=dict)  # node id -> display name
    extensions: dict[str, Extension] = field(default_factory=dict)
    automations: dict[str, Automation] = field(default_factory=dict)
    numbers: list[CarrierNumber] = field(default_factory=list)
    presence_state: str = "unknown"
    media_node_id: str | None = None
    sip: dict[str, Any] | None = None  # server, port, transport, realm: what a phone registers to
    browser_sip: dict[str, Any] | None = None
    calls: dict[str, CallInfo] = field(default_factory=dict)
    summary: Summary = field(default_factory=Summary)
    active_calls: int = 0
    total_calls: int = 0
    answered_calls: int = 0
    outbound_routes: list[dict[str, Any]] = field(default_factory=list)


def outbound_routes(snapshot: dict, extensions: dict[str, Extension], numbers: list[CarrierNumber]) -> list[dict[str, Any]]:
    """Project the outbound policies that already authorize physical and browser SIP calls."""
    enabled_nodes = {node["id"] for node in snapshot.get("nodes", []) if node.get("desired_enabled", True)}
    phones = {key: ext for key, ext in extensions.items() if ext.enabled and not ext.gateway and ext.node_id in enabled_nodes}
    routes = []
    for group in snapshot.get("gateway_route_sets", []):
        for route in group.get("routes", []):
            outbound = route.get("outbound")
            gateway = extensions.get(route.get("gateway_endpoint_id"))
            if not route.get("enabled") or not outbound or not gateway or not gateway.gateway or not gateway.enabled:
                continue
            sources = [phones[key].extension for key in outbound.get("source_ids", []) if key in phones]
            if sources:
                routes.append({"id": route["id"], "name": gateway.name, "prefix": outbound["access_prefix"], "extensions": sources})
    for number in numbers:
        code = number.airtel_access_code
        if not code:
            continue
        blocked = {group.get("node_id") for group in snapshot.get("route_sets", [])
                   if any(route.get("code") == code for route in group.get("routes", []))}
        blocked.update(group.get("node_id") for group in snapshot.get("gateway_route_sets", [])
                       if any(route.get("enabled") and (outbound := route.get("outbound"))
                              and outbound.get("access_prefix") and code.startswith(outbound["access_prefix"])
                              for route in group.get("routes", [])))
        sources = [ext.extension for ext in phones.values() if ext.node_id not in blocked]
        if sources:
            routes.append({"id": number.id, "name": f"Airtel · {number.number[-4:]}", "prefix": code, "extensions": sources})
    return sorted(routes, key=lambda route: (route["name"].casefold(), route["prefix"], route["id"]))


def build_extensions(snapshot: dict[str, Any], presence: dict[str, Any]) -> dict[str, Extension]:
    seen = {item.get("endpoint_id"): item for item in presence.get("endpoints", [])}
    result: dict[str, Extension] = {}
    for item in snapshot.get("endpoints", []):
        if item.get("retired"):
            continue
        observed = seen.get(item["id"]) or {}
        state = observed.get("state")
        result[item["id"]] = Extension(
            id=item["id"],
            name=item.get("display_name") or item.get("extension", ""),
            extension=item.get("extension", ""),
            node_id=item.get("node_id"),
            enabled=bool(item.get("desired_enabled")),
            revision=int(item.get("revision", 1)),
            credential_revision=int(item.get("credential_revision", 0)),
            gateway=bool(item.get("gateway")),
            online=True if state == "online" else False if state == "offline" else None,
            codecs=tuple(item.get("codecs") or ("PCMU", "PCMA")),
            observed_at=observed.get("observed_at"),
            registration_realm=observed.get("registration_realm"),
        )
    return result


def parse_automations(payloads: list[dict[str, Any]]) -> dict[str, Automation]:
    """Flatten the per-node automation lists into one mapping."""
    result: dict[str, Automation] = {}
    for payload in payloads:
        for item in payload.get("items", []):
            settings = item.get("settings") or {}
            result[item["id"]] = Automation(
                id=item["id"],
                name=settings.get("display_name", item["id"]),
                node_id=item.get("node_id", ""),
                source_id=settings.get("source_endpoint_id", ""),
                target_id=settings.get("target_endpoint_id", ""),
                enabled=bool(settings.get("enabled")),
                revision=int(item.get("revision", 1)),
                cooldown=int(settings.get("cooldown_sec", 0)),
                video=bool(settings.get("video")),
            )
    return result


def parse_numbers(items: list[dict[str, Any]]) -> list[CarrierNumber]:
    result = []
    for item in items:
        airtel = item.get("airtel") or {}
        code = airtel.get("access_code") if airtel.get("gateway_configured") else None
        result.append(CarrierNumber(id=item["id"], number=item["number"], source=item.get("source", ""), airtel_access_code=code))
    return result


def parse_runtime(presence: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Pick the enabled, applied voice node and the SIP address phones use."""
    runtimes = [item for item in presence.get("media_runtimes", []) if item.get("enabled")]
    runtimes.sort(key=lambda item: item.get("configuration_state") != "applied")
    if not runtimes:
        return None, None
    chosen = runtimes[0]
    return chosen.get("id"), chosen.get("sip_connection")


def parse_browser_listener(presence: dict[str, Any]) -> dict[str, Any] | None:
    for runtime in presence.get("media_runtimes", []):
        if runtime.get("enabled") and runtime.get("configuration_state") == "applied":
            listener = runtime.get("sip_connection") or {}
            port = listener.get("wss_port")
            if type(port) is int and 1024 <= port <= 65535 and listener.get("realm"):
                return {"realm": listener["realm"], "port": port}
    return None


def parse_calls(dashboard: dict[str, Any]) -> dict[str, CallInfo]:
    result: dict[str, CallInfo] = {}
    for item in (dashboard.get("calls") or {}).get("items", []):
        result[item["id"]] = CallInfo(
            id=item["id"],
            phase=item.get("phase", "ended"),
            revision=int(item.get("revision", 1)),
            started_at=item.get("started_at"),
            connected_at=item.get("connected_at"),
            ended_at=item.get("ended_at"),
            connected_seconds=int(item.get("connected_seconds") or 0),
        )
    return result


def parse_summary(dashboard: dict[str, Any]) -> Summary:
    raw = dashboard.get("summary") or {}
    return Summary(
        window_days=int(raw.get("window_days") or 0),
        calls=int(raw.get("calls") or 0),
        answered=int(raw.get("answered_calls") or 0),
        unanswered=int(raw.get("unanswered_calls") or 0),
        active_sessions=int(raw.get("active_sessions") or 0),
        connected_seconds=int(raw.get("connected_seconds") or 0),
    )


def history_rows(calls: dict[str, CallInfo], limit: int = 25) -> list[dict[str, Any]]:
    """Newest first, in the shape services return to scripts."""
    ordered = sorted(calls.values(), key=lambda call: call.started_at or "", reverse=True)
    return [
        {"call_id": c.id, "phase": c.phase, "started_at": c.started_at, "connected_at": c.connected_at, "ended_at": c.ended_at, "duration_seconds": c.connected_seconds, "answered": bool(c.connected_at)}
        for c in ordered[: max(1, min(limit, 100))]
    ]


def last_call_time(calls: dict[str, CallInfo]) -> str | None:
    starts = [call.started_at for call in calls.values() if call.started_at]
    return max(starts) if starts else None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_timestamp(value: str | None) -> datetime | None:
    """A timezone-aware datetime for a sensor, or None."""
    parsed = _parse_time(value)
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def diff_calls(previous: dict[str, CallInfo] | None, current: dict[str, CallInfo], now: datetime | None = None) -> list[CallEvent]:
    """Turn two snapshots of the call list into lifecycle events.

    The first snapshot (previous is None) is a baseline and produces nothing, so a
    restart never replays old calls. A call first seen already ended is reported
    only if it ended within the last two minutes.
    """
    if previous is None:
        return []
    now = now or datetime.now(timezone.utc)
    events: list[CallEvent] = []
    for call_id, call in current.items():
        before = previous.get(call_id)
        if before is None:
            if call.phase in PHASES_RINGING:
                events.append(CallEvent("incoming", call))
            elif call.phase == "active":
                events.append(CallEvent("incoming", call))
                events.append(CallEvent("answered", call))
            elif call.phase == "ended":
                ended = _parse_time(call.ended_at)
                if ended and now - ended <= timedelta(minutes=2):
                    events.append(CallEvent("ended" if call.connected_at else "missed", call))
            continue
        if before.phase == call.phase:
            continue
        if call.phase == "active" and before.phase != "active":
            events.append(CallEvent("answered", call))
        elif call.phase == "ended" and before.phase != "ended":
            answered = bool(call.connected_at) or before.phase == "active"
            events.append(CallEvent("ended" if answered else "missed", call))
    return events


def diff_presence(previous: dict[str, Extension] | None, current: dict[str, Extension]) -> list[tuple[Extension, str]]:
    """Phones that came online, went offline, were added or removed since last time.

    Returns (extension, change) with change in online, offline, added, removed.
    The first snapshot is a baseline. A phone whose status is unknown is never
    reported as offline, so losing sight of the voice service raises no alarms.
    """
    if previous is None:
        return []
    changes: list[tuple[Extension, str]] = []
    for ext_id, ext in current.items():
        before = previous.get(ext_id)
        if before is None:
            changes.append((ext, "added"))
        elif before.online is not None and ext.online is not None and before.online != ext.online:
            changes.append((ext, "online" if ext.online else "offline"))
    for ext_id, ext in previous.items():
        if ext_id not in current:
            changes.append((ext, "removed"))
    return changes


def interval_for(workspace: Workspace, idle: int, active: int) -> int:
    """Poll quickly while a call is in progress, slowly otherwise."""
    busy = workspace.active_calls > 0 or any(call.phase in (*PHASES_RINGING, "active") for call in workspace.calls.values())
    return active if busy else idle


LIVE_KINDS = {"ringing": "incoming", "answered": "answered", "ended": "ended", "missed": "missed"}
_PHASE_FOR = {"incoming": "ringing", "answered": "active", "ended": "ended", "missed": "ended"}


def _party(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    extension, name = value.get("extension"), value.get("name")
    if not isinstance(extension, str) or not isinstance(name, str):
        return None
    return {"extension": extension, "name": name}


def parse_live_event(data: Any) -> CallEvent | None:
    """Turn one stream message into a call event, or None when it is not one we report."""
    if not isinstance(data, dict):
        return None
    kind = LIVE_KINDS.get(str(data.get("kind")))
    call_id, seq = data.get("call_id"), data.get("seq")
    if kind is None or not isinstance(call_id, str) or isinstance(seq, bool) or not isinstance(seq, int):
        return None
    when = data.get("occurred_at") if isinstance(data.get("occurred_at"), str) else None
    revision = data.get("revision") if isinstance(data.get("revision"), int) else 0
    info = CallInfo(
        id=call_id,
        phase=_PHASE_FOR[kind],
        revision=revision,
        started_at=when if kind == "incoming" else None,
        connected_at=when if kind == "answered" else None,
        ended_at=when if kind in ("ended", "missed") else None,
        connected_seconds=0,
    )
    return CallEvent(kind, info, _party(data.get("from")), _party(data.get("to")), seq)
