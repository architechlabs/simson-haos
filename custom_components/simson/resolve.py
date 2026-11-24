"""Turn what a user typed into the identifiers the API needs (no Home Assistant imports)."""

from __future__ import annotations

import re

from .model import Automation, Extension, Workspace

EXTENSION = re.compile(r"^[1-9][0-9]{1,7}$")


class ResolveError(Exception):
    """The request cannot be carried out; the message is safe to show the user."""


def find_extension(workspace: Workspace, number: str) -> Extension:
    value = str(number).strip()
    if not EXTENSION.fullmatch(value):
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
        if workspace.nodes and not ext.node_id:
            raise ResolveError(f"Assign extension {ext.extension} to a phone group in Simson first.")
        if ext.gateway:
            raise ResolveError(f"Extension {ext.extension} is a carrier gateway. Use a browser SIP card for an authorized carrier route.")
    if not workspace.media_node_id:
        raise ResolveError("This location has no active voice service yet.")
    return workspace.media_node_id, source.id, target.id


def default_caller(workspace: Workspace, preferred: str | None = None) -> str:
    """The phone calls come from when a script does not say: the chosen one, else the first usable."""
    usable = sorted((ext for ext in workspace.extensions.values() if ext.enabled and not ext.gateway), key=lambda ext: (ext.online is not True, len(ext.extension), ext.extension))
    if preferred and any(ext.extension == str(preferred) for ext in usable):
        return str(preferred)
    if not usable:
        raise ResolveError("There is no enabled phone to call from. Enable a phone in Simson first.")
    return usable[0].extension


def find_automation(workspace: Workspace, wanted: str) -> Automation:
    """Find a call preset by its id or its name (case-insensitive)."""
    text = str(wanted).strip()
    if text in workspace.automations:
        return workspace.automations[text]
    matches = [item for item in workspace.automations.values() if item.name.casefold() == text.casefold()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ResolveError(f"More than one call preset is named “{text}”. Use its id.")
    raise ResolveError(f"There is no call preset “{text}” at this location.")


def runnable(automation: Automation) -> Automation:
    if not automation.enabled:
        raise ResolveError(f"The call preset “{automation.name}” is turned off.")
    return automation
