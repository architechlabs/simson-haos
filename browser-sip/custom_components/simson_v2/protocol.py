"""Validate the small, site-scoped call event and routing payloads."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import UUID

DOMAIN = "simson_v2"
PORTAL = "https://simson.architechlabs.in"
API = "https://api-simson.architechlabs.in"
STATES = ("ringing", "answered", "ended", "missed")
MAX_CALLS = 128
MAX_ROUTES = 64
EXTENSION = re.compile(r"[1-9][0-9]{1,7}")
HA_ID = re.compile(r"[0-9a-f]{32}")
DASHBOARD = re.compile(r"/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+){0,3}/?")


def uuid_text(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("Expected a canonical UUID")
    parsed = UUID(value)
    if str(parsed) != value or parsed.version not in range(1, 9):
        raise ValueError("Expected a canonical UUID")
    return value


def extension(value):
    if not isinstance(value, str) or not EXTENSION.fullmatch(value):
        raise ValueError("Expected a SIP extension")
    return value


def dashboard_path(value):
    if not isinstance(value, str) or len(value) > 180 or not DASHBOARD.fullmatch(value):
        raise ValueError("Expected a local dashboard path")
    return value


def label(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or not value.isprintable():
        raise ValueError("Expected a short label")
    return value


def parse_event(raw, site, now=None, *, recover_terminal=False):
    expected = {"site_id", "call_id", "revision", "state", "endpoint_id", "extension", "occurred_at"}
    if not isinstance(raw, dict) or not expected <= raw.keys() <= expected | {"caller"}:
        raise ValueError("Invalid call event fields")
    if uuid_text(raw["site_id"]) != site or raw["state"] not in STATES:
        raise ValueError("Invalid call site or state")
    if type(raw["revision"]) is not int or not 1 <= raw["revision"] <= 2**53 - 1:
        raise ValueError("Invalid call event revision")
    if not isinstance(raw["occurred_at"], str) or len(raw["occurred_at"]) > 40:
        raise ValueError("Invalid call timestamp")
    occurred = datetime.fromisoformat(raw["occurred_at"].replace("Z", "+00:00"))
    if occurred.tzinfo is None:
        raise ValueError("Call timestamp needs a timezone")
    age = ((now or datetime.now(timezone.utc)) - occurred).total_seconds()
    limit = 45 if raw["state"] == "ringing" else 120
    if recover_terminal and raw["state"] in ("ended", "missed"):
        limit = 3600
    if not -10 <= age <= limit:
        raise ValueError("Call event is outside its delivery window")
    return {
        "site_id": site, "call_id": uuid_text(raw["call_id"]), "revision": raw["revision"],
        "endpoint_id": uuid_text(raw["endpoint_id"]), "extension": extension(raw["extension"]), "state": raw["state"],
        "occurred_at": occurred.astimezone(timezone.utc).isoformat(),
        "caller": label(raw["caller"]) if raw.get("caller") else "Incoming caller",
    }
