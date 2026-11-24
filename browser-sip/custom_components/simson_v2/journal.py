"""Bounded per-location replay checkpoint. Only non-secret projections are stored."""
from collections import OrderedDict
from datetime import datetime, timezone

from .protocol import MAX_CALLS, STATES, extension, uuid_text

MAX_SEEN = 512
MAX_SEQ = (1 << 63) - 1


def sequence(value):
    if (
        not isinstance(value, str) or not value.isascii() or not value.isdecimal()
        or len(value) > 19 or (len(value) > 1 and value.startswith("0"))
    ):
        raise ValueError("Invalid event sequence")
    number = int(value)
    if number > MAX_SEQ:
        raise ValueError("Invalid event sequence")
    return number


def stored_event(raw, site_id):
    """Rebuild a restricted event. Never copy caller labels into storage."""
    if not isinstance(raw, dict) or raw.get("site_id") != site_id or raw.get("state") not in STATES:
        raise ValueError("Invalid event")
    revision = raw.get("revision")
    at = raw.get("occurred_at")
    if type(revision) is not int or not 1 <= revision < 1 << 53 or not isinstance(at, str) or len(at) > 40:
        raise ValueError("Invalid event")
    stamp = datetime.fromisoformat(at)
    if stamp.utcoffset() is None:
        raise ValueError("Invalid event time")
    return {
        "site_id": site_id, "call_id": uuid_text(raw.get("call_id")),
        "endpoint_id": uuid_text(raw.get("endpoint_id")), "extension": extension(raw.get("extension")),
        "revision": revision, "state": raw["state"], "occurred_at": stamp.astimezone(timezone.utc).isoformat(),
    }


class Journal:
    def __init__(self, tenant, site, data=None):
        self.tenant = tenant
        self.site = site
        self.cursor = None
        self.baseline = 0
        self.seen = set()
        self.calls = OrderedDict()
        self.totals = {state: 0 for state in STATES}
        self.last = None
        if isinstance(data, dict) and (data.get("tenant"), data.get("site")) == (tenant, site):
            self.restore(data)

    def restore(self, data):
        try:
            cursor = sequence(data["cursor"]) if data.get("cursor") is not None else None
            baseline = sequence(data.get("baseline", "0"))
            if baseline > (cursor or 0):
                raise ValueError("Invalid baseline")
            seen = {sequence(item) for item in data["seen"][:MAX_SEEN]}
            events = [stored_event(item, self.site) for item in data["calls"][:MAX_CALLS]]
            totals = {state: data["totals"].get(state, 0) for state in STATES}
            if any(type(value) is not int or not 0 <= value < 1 << 53 for value in totals.values()):
                raise ValueError("Invalid counters")
            last = stored_event(data["last"], self.site) if data.get("last") else None
        except (AttributeError, KeyError, TypeError, ValueError):
            return
        self.cursor = cursor
        self.baseline = baseline
        self.seen = {item for item in seen if cursor is not None and item <= cursor}
        self.calls.update((event["call_id"], event) for event in events)
        self.totals = totals
        self.last = last

    def data(self):
        return {
            "tenant": self.tenant, "site": self.site,
            "cursor": str(self.cursor) if self.cursor is not None else None,
            "baseline": str(self.baseline),
            "seen": [str(item) for item in sorted(self.seen)],
            "calls": list(self.calls.values()), "last": self.last, "totals": dict(self.totals),
        }

    def advance(self, identifier, ready=False):
        if ready:
            if self.cursor is None:
                self.cursor = identifier
                self.baseline = identifier
                return True
            return False
        if identifier <= self.baseline or identifier in self.seen:
            return False
        self.cursor = max(self.cursor or 0, identifier)
        self.seen.add(identifier)
        if len(self.seen) > MAX_SEEN:
            self.seen = set(sorted(self.seen)[-MAX_SEEN:])
        return True

    def record(self, event):
        clean = stored_event(event, self.site)
        previous = self.calls.get(clean["call_id"])
        if previous and (
            clean["revision"] <= previous["revision"]
            or clean["endpoint_id"] != previous["endpoint_id"]
            or previous["state"] in ("missed", "ended")
            or previous["state"] == "answered" and clean["state"] == "ringing"
        ):
            return False
        self.calls[clean["call_id"]] = clean
        self.calls.move_to_end(clean["call_id"])
        if len(self.calls) > MAX_CALLS:
            self.calls.popitem(last=False)
        self.totals[clean["state"]] += 1
        self.last = clean
        return True
