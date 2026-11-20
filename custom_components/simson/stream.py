"""Keep one live event stream open for a Simson location, and reconnect when it drops."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from homeassistant.core import HomeAssistant

from .api import SimsonApi, SimsonAuthError, SimsonError, SimsonNotFound, SimsonPermissionError
from .model import CallEvent, parse_live_event
from .sse import backoff_seconds

_LOGGER = logging.getLogger(__name__)


class EventStreamer:
    """Runs in the background. Falls back silently to polling when the server cannot stream."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SimsonApi,
        tenant: str,
        *,
        on_event: Callable[[CallEvent], None],
        on_state: Callable[[bool], None],
        on_auth_failed: Callable[[], None],
    ) -> None:
        self._hass, self._api, self._tenant = hass, api, tenant
        self._on_event, self._on_state, self._on_auth_failed = on_event, on_state, on_auth_failed
        self._task: asyncio.Task | None = None
        self._last_id: str | None = None
        self.connected = False

    def start(self) -> None:
        if self._task is None:
            self._task = self._hass.async_create_background_task(self._run(), "simson live events")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._set(False)

    def _set(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            self._on_state(connected)

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                async for message in self._api.events(self._tenant, self._last_id):
                    if message.id is not None:
                        self._last_id = message.id
                    if message.event == "ready":
                        attempt = 0
                        self._set(True)
                        continue
                    if message.event != "call":
                        continue
                    try:
                        event = parse_live_event(json.loads(message.data))
                    except ValueError:
                        continue
                    if event is not None:
                        self._on_event(event)
                # The server closes a stream after a few minutes on purpose: reconnect at once.
                self._set(False)
                continue
            except asyncio.CancelledError:
                raise
            except SimsonAuthError:
                self._set(False)
                self._on_auth_failed()
                return
            except (SimsonPermissionError, SimsonNotFound):
                # Old sign-in without the events permission, or an older server. Polling still works.
                _LOGGER.info("Live Simson events are not available for this connection; using polling. Reconnect the integration to enable them.")
                self._set(False)
                return
            except SimsonError as error:
                _LOGGER.debug("Simson event stream dropped: %s", error)
            except Exception:  # noqa: BLE001 - the stream must never take Home Assistant down
                _LOGGER.exception("Unexpected error in the Simson event stream")
            self._set(False)
            await asyncio.sleep(backoff_seconds(attempt))
            attempt += 1
