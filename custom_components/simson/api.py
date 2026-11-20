"""Async client for the Simson integration API.

Kept free of Home Assistant imports: it takes an aiohttp session and an async
callable that returns a currently valid access token. Home Assistant's OAuth2
session supplies that callable and refreshes tokens, so this client never stores
or renews credentials itself.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .credential import OneTimeKey, credential_context

TokenProvider = Callable[[], Awaitable[str]]


class SimsonError(Exception):
    """Base class for every client error."""


class SimsonAuthError(SimsonError):
    """The token was rejected. The user must sign in again."""


class SimsonPermissionError(SimsonError):
    """The token is valid but its scopes or the user's role forbid the call."""


class SimsonPlanError(SimsonError):
    """The workspace plan does not include this feature."""


class SimsonNotFound(SimsonError):
    """The workspace, location, extension or call no longer exists."""


class SimsonConflict(SimsonError):
    """The record changed. Reload it and try again."""


class SimsonRateLimited(SimsonError):
    """Too many requests."""


class SimsonConnectionError(SimsonError):
    """Simson could not be reached or answered with a server error."""


class SimsonApiError(SimsonError):
    """Unexpected response."""


_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=6)


class SimsonApi:
    """Thin, typed-by-convention wrapper over the REST API."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, token: TokenProvider) -> None:
        self._session = session
        self._base = base_url.rstrip("/") + "/integration"
        self._token = token

    async def _request(self, method: str, path: str, *, body: Any = None, key: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {await self._token()}", "Accept": "application/json"}
        if method != "GET":
            headers["Idempotency-Key"] = key or str(uuid.uuid4())
        try:
            async with self._session.request(method, self._base + path, json=body, headers=headers, timeout=_TIMEOUT, allow_redirects=False) as response:
                status = response.status
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    payload = None
                if status == 401:
                    raise SimsonAuthError("Simson rejected the access token.")
                if status == 402:
                    raise SimsonPlanError("This feature is not included in the workspace plan.")
                if status == 403:
                    raise SimsonPermissionError("This account may not do that in the workspace.")
                if status == 404:
                    raise SimsonNotFound("That record no longer exists.")
                if status == 409:
                    raise SimsonConflict("The record changed. Try again.")
                if status == 429:
                    raise SimsonRateLimited("Too many requests.")
                if status >= 500:
                    raise SimsonConnectionError(f"Simson is unavailable (HTTP {status}).")
                if 300 <= status < 400:
                    raise SimsonApiError("Simson redirected the request, which is never expected.")
                if status >= 400:
                    raise SimsonApiError(f"Simson rejected the request (HTTP {status}).")
                if payload is None and status != 204:
                    raise SimsonApiError("Simson returned an unreadable response.")
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            raise SimsonConnectionError("Simson could not be reached.") from error

    # ---- reading ----------------------------------------------------------

    async def me(self) -> dict:
        return await self._request("GET", "/v1/me")

    async def sites(self, tenant: str) -> list[dict]:
        return (await self._request("GET", f"/v1/tenants/{tenant}/sites")).get("items", [])

    async def snapshot(self, tenant: str, site: str) -> dict:
        return await self._request("GET", f"/v1/tenants/{tenant}/sites/{site}/snapshot")

    async def presence(self, tenant: str, site: str) -> dict:
        return await self._request("GET", f"/v1/tenants/{tenant}/sites/{site}/presence")

    async def numbers(self, tenant: str, site: str) -> list[dict]:
        return (await self._request("GET", f"/v1/tenants/{tenant}/sites/{site}/numbers")).get("items", [])

    async def call_dashboard(self, tenant: str, *, after: str | None = None, limit: int | None = None) -> dict:
        query = "&".join(part for part in (f"after={after}" if after else "", f"limit={limit}" if limit else "") if part)
        return await self._request("GET", f"/v1/tenants/{tenant}/call-dashboard" + (f"?{query}" if query else ""))

    async def automations(self, tenant: str, site: str, node: str) -> dict:
        return await self._request("GET", f"/v1/tenants/{tenant}/sites/{site}/nodes/{node}/automations")

    async def run_automation(self, tenant: str, site: str, node: str, automation: str, revision: int) -> dict:
        """Run a saved call preset now. The event id doubles as the idempotency key, so a retry never rings twice."""
        event = str(uuid.uuid4())
        body = {"event_id": event, "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "expected_revision": revision}
        return await self._request("POST", f"/v1/tenants/{tenant}/sites/{site}/nodes/{node}/automations/{automation}/trigger", body=body, key=event)

    # ---- extensions ---------------------------------------------------------

    async def create_extension(self, tenant: str, site: str, display_name: str, extension: str, *, codecs: tuple[str, ...] = ("PCMU", "PCMA"), enabled: bool = True) -> dict:
        body = {"display_name": display_name, "extension": extension, "codecs": list(codecs), "desired_enabled": enabled}
        return await self._request("POST", f"/v1/tenants/{tenant}/sites/{site}/sip-endpoints", body=body)

    async def update_extension(self, tenant: str, site: str, endpoint: str, *, display_name: str, extension: str, codecs: list[str], enabled: bool, revision: int) -> dict:
        body = {"display_name": display_name, "extension": extension, "codecs": codecs, "desired_enabled": enabled, "expected_revision": revision}
        return await self._request("PATCH", f"/v1/tenants/{tenant}/sites/{site}/sip-endpoints/{endpoint}", body=body)

    async def delete_extension(self, tenant: str, site: str, endpoint: str, revision: int) -> dict:
        return await self._request("DELETE", f"/v1/tenants/{tenant}/sites/{site}/sip-endpoints/{endpoint}", body={"expected_revision": revision})

    async def issue_password(self, tenant: str, site: str, endpoint: str, credential_revision: int) -> str:
        """Create a new SIP password and return it once, in clear text.

        The server seals the password to a one-time key generated here, so it never
        crosses the network or any log in the clear.
        """
        key = OneTimeKey.generate()
        result = await self._request(
            "PUT",
            f"/v1/tenants/{tenant}/sites/{site}/sip-endpoints/{endpoint}/credential",
            body={"public_key": key.public_key, "expected_revision": credential_revision},
        )
        return key.open(result, credential_context(tenant, site, endpoint))

    # ---- calls ------------------------------------------------------------

    async def start_call(self, tenant: str, site: str, node: str, source: str, target: str, *, timeout: int = 30, video: bool = False, key: str | None = None) -> dict:
        body: dict[str, Any] = {"site_id": site, "media_node_id": node, "source_endpoint_id": source, "target_endpoint_id": target, "timeout_sec": timeout}
        if video:
            body["video"] = True
        return await self._request("POST", f"/v1/tenants/{tenant}/call-intents", body=body, key=key)

    async def call_intent(self, tenant: str, call_id: str) -> dict:
        return await self._request("GET", f"/v1/tenants/{tenant}/call-intents/{call_id}")

    async def cancel_call(self, tenant: str, call_id: str, revision: int) -> dict:
        return await self._request("POST", f"/v1/tenants/{tenant}/call-intents/{call_id}/cancel", body={"expected_revision": revision})

    async def hang_up(self, tenant: str, site: str, call_id: str, revision: int) -> dict:
        return await self._request("POST", f"/v1/tenants/{tenant}/sites/{site}/calls/{call_id}/disconnect", body={"expected_revision": revision})
