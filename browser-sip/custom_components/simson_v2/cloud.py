"""OAuth and reconnecting call events using Simson's existing integration grant."""
from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from datetime import datetime, timezone
from random import uniform
from time import monotonic

from aiohttp import ClientError, ClientTimeout
from cryptography.fernet import Fernet, InvalidToken
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce, MY_AUTH_CALLBACK_PATH,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .protocol import API, DOMAIN, PORTAL, parse_event, uuid_text
from .journal import sequence

CLIENT_ID = "home-assistant"
SCOPES = "workspace.read events.read"
PRIVATE_DIR = "/share/simson-v2-private"
TOKEN = re.compile(r"simson_(?:at|rt)_[A-Za-z0-9_-]{43}")


class Reauthorize(Exception):
    """The owner needs to approve the integration again."""


class CloudUnavailable(Exception):
    """The approved Simson integration is temporarily unreachable."""

    def __init__(self, retry_after=0):
        self.retry_after = retry_after


def storage_cipher():
    directory = os.open(PRIVATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open("oauth.key", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or not 1 <= info.st_size <= 80:
                raise ValueError("Invalid storage key file")
            return Fernet(handle.read(81).strip())
    finally:
        os.close(directory)


async def bounded_json(response, maximum):
    parts = bytearray()
    async for chunk in response.content.iter_chunked(4096):
        if len(parts) + len(chunk) > maximum:
            raise CloudUnavailable
        parts.extend(chunk)
    try:
        return json.loads(parts)
    except (UnicodeError, ValueError):
        raise CloudUnavailable from None


async def token_request(hass, fields):
    try:
        async with async_get_clientsession(hass).post(
            f"{API}/oauth/token", data={**fields, "client_id": CLIENT_ID},
            allow_redirects=False, timeout=ClientTimeout(total=8),
        ) as response:
            if response.status == 400:
                raise Reauthorize
            if response.status != 200:
                raise CloudUnavailable
            value = await bounded_json(response, 8192)
    except (ClientError, TimeoutError):
        raise CloudUnavailable from None
    scope = value.get("scope") if isinstance(value, dict) else None
    if (
        not isinstance(scope, str) or set(scope.split()) != set(SCOPES.split())
        or not isinstance(value.get("expires_in"), int) or not 60 <= value["expires_in"] <= 3600
        or not isinstance(value.get("access_token"), str) or not TOKEN.fullmatch(value["access_token"])
        or not isinstance(value.get("refresh_token"), str) or not TOKEN.fullmatch(value["refresh_token"])
        or not value["access_token"].startswith("simson_at_") or not value["refresh_token"].startswith("simson_rt_")
        or value.get("token_type") != "Bearer"
    ):
        raise CloudUnavailable
    return value


class SimsonOAuth(LocalOAuth2ImplementationWithPkce):
    def __init__(self, hass):
        super().__init__(hass, DOMAIN, CLIENT_ID, f"{PORTAL}/integrations/authorize/", f"{API}/oauth/token")

    @property
    def redirect_uri(self):
        return MY_AUTH_CALLBACK_PATH

    @property
    def extra_authorize_data(self):
        return {**super().extra_authorize_data, "scope": SCOPES}

    async def _token_request(self, data):
        return await token_request(self.hass, data)


def api_path(tenant, site=None):
    base = f"{API}/integration/v1/tenants/{uuid_text(tenant)}"
    return f"{base}/sites/{uuid_text(site)}" if site else base


def protect_refresh(cipher, tenant, site, refresh):
    return cipher.encrypt(json.dumps([tenant, site, refresh], separators=(",", ":")).encode()).decode()


def open_refresh(cipher, data):
    try:
        tenant, site, refresh = json.loads(cipher.decrypt(data["oauth_ciphertext"].encode()))
        if (tenant, site) != (data["tenant_id"], data["site_id"]) or not isinstance(refresh, str) or not TOKEN.fullmatch(refresh) or not refresh.startswith("simson_rt_"):
            raise ValueError
        return refresh
    except (InvalidToken, KeyError, ValueError):
        raise Reauthorize from None


async def revoke(hass, entry):
    cipher = await hass.async_add_executor_job(storage_cipher)
    refresh = open_refresh(cipher, entry.data)
    async with async_get_clientsession(hass).post(
        f"{API}/oauth/revoke", data={"token": refresh}, allow_redirects=False,
        timeout=ClientTimeout(total=5),
    ) as response:
        return response.status == 200


async def cloud_get(hass, endpoint, access, maximum=128 << 10):
    try:
        async with async_get_clientsession(hass).get(
            endpoint, headers={"Authorization": f"Bearer {access}"}, allow_redirects=False,
            timeout=ClientTimeout(total=8),
        ) as response:
            if response.status in (401, 403):
                raise Reauthorize
            if response.status != 200:
                raise CloudUnavailable
            return await bounded_json(response, maximum)
    except (ClientError, TimeoutError):
        raise CloudUnavailable from None


class CallFeed:
    def __init__(self, site, cipher):
        self.site = site
        self.hass = site.hass
        self.entry = site.entry
        self.cipher = cipher
        self.access_token = None
        self.expires = 0
        self.refresh_lock = asyncio.Lock()
        self.tenant_id = self.entry.data["tenant_id"]

    async def access(self):
        async with self.refresh_lock:
            if self.expires <= monotonic() + 30:
                refresh = open_refresh(self.cipher, self.entry.data)
                token = await token_request(self.hass, {"grant_type": "refresh_token", "refresh_token": refresh})
                encrypted = protect_refresh(self.cipher, self.tenant_id, self.site.site_id, token["refresh_token"])
                self.hass.config_entries.async_update_entry(self.entry, data={**self.entry.data, "oauth_ciphertext": encrypted})
                self.access_token = token["access_token"]
                self.expires = monotonic() + token["expires_in"]
            return self.access_token

    def reauthorize(self):
        if self.site.connection != "sign_in_required":
            self.status("sign_in_required")
            self.entry.async_start_reauth(self.hass)

    def status(self, status):
        if self.site.connection == status:
            return
        self.site.connection = status
        async_dispatcher_send(self.hass, self.site.signal)

    async def run(self):
        delay = 1
        while True:
            try:
                await self.read()
                delay = 1
            except Reauthorize:
                self.reauthorize()
                return
            except (ClientError, TimeoutError, ValueError, CloudUnavailable) as exc:
                self.status("reconnecting")
                hint = exc.retry_after if isinstance(exc, CloudUnavailable) else 0
                await asyncio.sleep(max(hint, delay + uniform(0, delay * .25)))
                delay = min(delay * 2, 30)

    async def read(self):
        used = await self.access()
        headers = {"Authorization": f"Bearer {used}", "Accept": "text/event-stream"}
        journal = self.site.journal
        if journal.cursor is not None:
            headers["Last-Event-ID"] = str(journal.cursor)
        started = monotonic()
        async with async_get_clientsession(self.hass).get(
            f"{api_path(self.tenant_id, self.site.site_id)}/events", headers=headers, allow_redirects=False,
            timeout=ClientTimeout(total=85, sock_read=25),
        ) as response:
            if response.status == 401:
                if used == self.access_token:
                    self.expires = 0
                raise CloudUnavailable
            if response.status == 403:
                raise Reauthorize
            if response.status in (429, 503):
                hint = response.headers.get("Retry-After", "")
                raise CloudUnavailable(min(60, int(hint)) if hint.isascii() and hint.isdecimal() and len(hint) < 5 else 0)
            if response.status != 200 or response.content_type != "text/event-stream":
                raise CloudUnavailable
            if self.site.connection != "connected":
                self.status("recovering")
            caught_up = False
            event_type = data = identifier = None
            async for raw in response.content:
                if len(raw) > 8192:
                    raise CloudUnavailable
                line = raw.rstrip(b"\r\n")
                if not line:
                    if identifier is not None and event_type == b"ready" and journal.advance(identifier, ready=True):
                        self.site.save_soon()
                    elif identifier is not None and event_type == b"call" and data and journal.advance(identifier):
                        await self.receive(data, replayed=not caught_up)
                        self.site.save_soon()
                    if event_type == b"caught_up" and not caught_up:
                        caught_up = True
                        self.status("connected")
                        self.site.finish_replay()
                    event_type = data = identifier = None
                elif line.startswith(b": keep-alive") and not caught_up:
                    # Compatible with servers that predate the catch-up boundary.
                    caught_up = True
                    self.status("connected")
                    self.site.finish_replay()
                elif line.startswith(b"event: "):
                    event_type = line[7:]
                elif line.startswith(b"data: "):
                    data = line[6:]
                elif line.startswith(b"id: "):
                    identifier = sequence(line[4:].decode("ascii"))
            if not caught_up or monotonic() - started < 20:
                raise CloudUnavailable

    async def receive(self, body, *, replayed):
        try:
            value = json.loads(body)
            if value["site_id"] != self.site.site_id or not value.get("to"):
                return
            source = value.get("from")
            label = source["name"][:80] if source else ""
            call_id = value.get("offer_id") or value["call_id"]
            event = parse_event({
                "site_id": value["site_id"], "call_id": call_id, "revision": value["revision"],
                "state": value["kind"], "endpoint_id": value["to"]["id"], "extension": value["to"]["extension"],
                "occurred_at": value["occurred_at"], "caller": label,
            }, self.site.site_id, recover_terminal=replayed and call_id in self.site.calls)
        except (KeyError, AttributeError, TypeError, ValueError):
            return
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(event["occurred_at"])).total_seconds()
        await self.site.ingest(event, replayed=replayed, silent=age > 120)
