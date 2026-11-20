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
    calls: dict[str, CallInfo] = field(default_factory=dict)
    summary: Summary = field(default_factory=Summary)
    active_calls: int = 0
    total_calls: int = 0
    answered_calls: int = 0


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
    return [CarrierNumber(id=item["id"], number=item["number"], source=item.get("source", "")) for item in items]


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
