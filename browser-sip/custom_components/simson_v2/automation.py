"""Submit only preconfigured Simson automation webhooks."""
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import stat
from uuid import uuid4

from aiohttp import ClientError, ClientTimeout
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
import voluptuous as vol

from .protocol import API, DOMAIN, uuid_text
from .cloud import PRIVATE_DIR
from .transport import get_site

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
TOKEN = re.compile(r"simson_wh_[A-Za-z0-9_-]{43}")


def read_automation_key(site_id, name):
    # Keep credentials out of config entries, services and HA configuration backups.
    root = Path(PRIVATE_DIR)
    directory = root / uuid_text(site_id)
    if not NAME.fullmatch(name):
        raise ValueError("Invalid automation name")
    # dir_fd and O_NOFOLLOW pin each directory and reject symlinks.
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    try:
        site_fd = os.open(directory.name, directory_flags, dir_fd=root_fd)
        try:
            fd = os.open(f"{name}.key", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=site_fd)
            with os.fdopen(fd, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or not 1 <= info.st_size <= 128:
                    raise ValueError("Invalid automation key file")
                credential = file.read(129).decode("ascii").strip()
        finally:
            os.close(site_fd)
    finally:
        os.close(root_fd)
    if not TOKEN.fullmatch(credential):
        raise ValueError("Invalid automation credential")
    return credential


async def async_route_automation(hass, call):
    if call.context.user_id:
        user = await hass.auth.async_get_user(call.context.user_id)
        if not user or not user.is_active or not user.is_admin:
            raise HomeAssistantError("Only a Home Assistant administrator may run this action directly.")
    site = get_site(hass, call.data["site_id"])
    if site is None:
        raise HomeAssistantError("Select a configured Simson site.")
    name = call.data["automation"]
    try:
        key = await hass.async_add_executor_job(read_automation_key, site.site_id, name)
    except (AttributeError, OSError, ValueError):
        raise HomeAssistantError("Install the scoped automation key on this Home Assistant host.") from None
    try:
        event_id = uuid_text(call.data.get("event_id") or str(uuid4()))
        occurred_at = call.data.get("occurred_at") or datetime.now(timezone.utc).isoformat()
        stamp = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
    except ValueError:
        raise HomeAssistantError("Supply a UUID and a timestamp with timezone for a retry.") from None
    payload = {"event_id": event_id, "occurred_at": stamp.astimezone(timezone.utc).isoformat()}
    try:
        session = async_get_clientsession(hass)
        async with session.post(
            f"{API}/v1/automation-webhooks/trigger", headers={"Authorization": f"Bearer {key}"},
            json=payload, allow_redirects=False, timeout=ClientTimeout(total=7),
        ) as response:
            code = response.status
            retry = response.headers.get("Retry-After", "")
    except (ClientError, TimeoutError):
        raise HomeAssistantError("Simson did not acknowledge the trigger. Retry with the same event ID and timestamp.") from None
    if code == 429 and retry.isdecimal() and 1 <= int(retry) <= 3600:
        raise HomeAssistantError(f"This automation can run again in {retry} seconds.")
    if code != 202:
        raise HomeAssistantError({
            401: "The assigned Simson automation key was rejected.",
            409: "Simson rejected this retry or a phone is busy.",
            503: "Call automation is temporarily unavailable.",
        }.get(code, "Simson rejected this automation trigger."))
    result = {"site_id": site.site_id, "automation": name, "event_id": event_id, "status": "queued"}
    site.last_automation = result
    hass.bus.async_fire(f"{DOMAIN}_automation", result)
    async_dispatcher_send(hass, site.automation_signal, result)
    async_dispatcher_send(hass, site.signal)


def register_automation(hass):
    async def trigger(call):
        await async_route_automation(hass, call)

    hass.services.async_register(DOMAIN, "trigger_automation", trigger, schema=vol.Schema({
        vol.Required("site_id"): str,
        vol.Required("automation"): vol.Match(NAME),
        vol.Inclusive("event_id", "retry"): str,
        vol.Inclusive("occurred_at", "retry"): vol.All(str, vol.Length(max=40)),
    }))
