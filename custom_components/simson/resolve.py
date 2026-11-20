"""Turn what a user typed into the identifiers the API needs (no Home Assistant imports)."""

from __future__ import annotations

import re
from typing import Any

from .model import Extension, Workspace

EXTENSION = re.compile(r"^[1-9][0-9]{1,7}$")


class ResolveError(Exception):
    """The request cannot be carried out; the message is safe to show the user."""


def find_extension(workspace: Workspace, number: str) -> Extension:
    value = str(number).strip()
    if not EXTENSION.match(value):
        raise ResolveError(f"“{number}” is not a valid extension number.")
    for extension in workspace.extensions.values():
        if extension.extension == value:
            return extension
    raise ResolveError(f"There is no extension {value} at this location.")


def plan_call(workspace: Workspace, from_extension: str, to_extension: str) -> tuple[str, str, str]:
    """Return (media node id, source endpoint id, target endpoint id) for a phone-to-phone call."""
    source, target = find_extension(workspace, from_extension), find_extension(workspace, to_extension)
    if source.id == target.id:
        raise ResolveError("A phone cannot call itself.")
    for ext in (source, target):
        if not ext.enabled:
            raise ResolveError(f"Extension {ext.extension} is turned off.")
        if ext.gateway:
            raise ResolveError(f"Extension {ext.extension} is a carrier gateway. Calls to outside numbers are placed from the Simson dashboard for now.")
    if not workspace.media_node_id:
        raise ResolveError("This location has no active voice service yet.")
    return workspace.media_node_id, source.id, target.id


def validate_new_extension(workspace: Workspace, number: str, name: str) -> tuple[str, str]:
    value, label = str(number).strip(), str(name).strip()
    if not EXTENSION.match(value):
        raise ResolveError("Use 2 to 8 digits for the extension, not starting with 0.")
    if not 1 <= len(label) <= 200:
        raise ResolveError("Give the phone a name.")
    if any(ext.extension == value for ext in workspace.extensions.values()):
        raise ResolveError(f"Extension {value} already exists.")
    return value, label


def phone_settings(workspace: Workspace, extension: str, password: str | None = None) -> dict[str, Any]:
    """What a person types into a SIP phone. The password is only present when just issued."""
    sip = workspace.sip or {}
    result: dict[str, Any] = {
        "extension": extension,
        "username": extension,
        "server": sip.get("server"),
        "port": sip.get("port"),
        "transport": sip.get("transport"),
        "realm": sip.get("realm"),
    }
    if password is not None:
        result["password"] = password
    return result
