"""Plain data model and call-event detection (no Home Assistant imports)."""

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


@dataclass
class Workspace:
    nodes: dict[str, str] = field(default_factory=dict)  # node id -> display name
    extensions: dict[str, Extension] = field(default_factory=dict)
    presence_state: str = "unknown"
    media_node_id: str | None = None
    sip: dict[str, Any] | None = None  # server, port, transport, realm: what a phone registers to
    calls: dict[str, CallInfo] = field(default_factory=dict)
    active_calls: int = 0
    total_calls: int = 0
    answered_calls: int = 0


def build_extensions(snapshot: dict[str, Any], presence: dict[str, Any]) -> dict[str, Extension]:
    states = {item.get("endpoint_id"): item.get("state") for item in presence.get("endpoints", [])}
    result: dict[str, Extension] = {}
    for item in snapshot.get("endpoints", []):
        if item.get("retired"):
            continue
        state = states.get(item["id"])
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
        )
    return result


def parse_runtime(presence: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Pick the enabled, applied voice node and the SIP address phones use."""
    runtimes = [item for item in presence.get("media_runtimes", []) if item.get("enabled")]
    runtimes.sort(key=lambda item: item.get("configuration_state") != "applied")
    if not runtimes:
        return None, None
    chosen = runtimes[0]
    return chosen.get("id"), chosen.get("sip_connection")


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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def interval_for(workspace: Workspace, idle: int, active: int) -> int:
    """Poll quickly while a call is in progress, slowly otherwise."""
    busy = workspace.active_calls > 0 or any(call.phase in (*PHASES_RINGING, "active") for call in workspace.calls.values())
    return active if busy else idle
