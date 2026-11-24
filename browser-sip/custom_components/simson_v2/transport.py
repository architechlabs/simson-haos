"""The authenticated Home Assistant integration API."""
from __future__ import annotations

import asyncio
import json

from aiohttp import web
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.const import KEY_HASS, KEY_HASS_USER
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
import voluptuous as vol

from .companion import active_users, companion_devices
from .protocol import DOMAIN, MAX_ROUTES, dashboard_path, extension, parse_event, uuid_text

SITE = {vol.Required("site_id"): str}


def get_site(hass, site_id):
    try:
        return hass.data[DOMAIN]["sites"].get(uuid_text(site_id))
    except ValueError:
        return None


def route_data(site):
    return [{"endpoint_id": endpoint, **route} for endpoint, route in sorted(site.routes.items())]


class CallWebhook(HomeAssistantView):
    """Receive call state from a trusted dispatcher authenticated by Home Assistant."""

    name = "api:simson_v2:call_webhook"
    url = "/api/simson_v2/sites/{site_id}/call-events"
    requires_auth = True

    async def post(self, request, site_id):
        actor = request[KEY_HASS_USER]
        if not actor.is_active or not actor.is_admin:
            raise web.HTTPForbidden()
        site = get_site(request.app[KEY_HASS], site_id)
        if site is None:
            raise web.HTTPNotFound()
        if request.query_string or request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            async with asyncio.timeout(5):
                body = await request.content.readexactly(request.content_length) if (
                    request.content_length is not None and 0 < request.content_length <= 4096
                ) else None
            event = parse_event(json.loads(body), site.site_id) if body else None
        except (asyncio.IncompleteReadError, TimeoutError, TypeError, ValueError):
            raise web.HTTPBadRequest() from None
        if event is None:
            raise web.HTTPBadRequest()
        return self.json({"accepted": await site.ingest(event)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/directory", **SITE})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_directory(hass, connection, msg):
    site = get_site(hass, msg["site_id"])
    if site is None:
        connection.send_error(msg["id"], "not_found", "Add this location under Simson V2 in Home Assistant first.")
        return
    devices = companion_devices(hass)
    users = await active_users(hass)
    rows = [
        {"id": identifier, "name": (user.name or "Home Assistant user")[:80],
         "devices": [{"id": device, "name": name} for device, (name, _) in devices.get(identifier, {}).items()][:16]}
        for identifier, user in sorted(users.items(), key=lambda item: ((item[1].name or "").casefold(), item[0]))
    ][:128]
    connection.send_result(msg["id"], {"users": rows, "routes": route_data(site)})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/set_route", **SITE,
    vol.Required("endpoint_id"): str, vol.Required("extension"): str, vol.Required("user_id"): vol.Any(str, None),
    vol.Required("devices"): vol.All([str], vol.Length(max=16)),
    vol.Required("dashboard_path"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_route(hass, connection, msg):
    site = get_site(hass, msg["site_id"])
    if site is None:
        connection.send_error(msg["id"], "not_found", "Add this location under Simson V2 in Home Assistant first.")
        return
    try:
        await save_route(hass, site, msg["endpoint_id"], msg["extension"], msg["user_id"], msg["devices"], msg["dashboard_path"])
    except ValueError:
        connection.send_error(msg["id"], "invalid_route", "Select an enabled extension, an active user and only their registered phones. Use a local dashboard path.")
        return
    connection.send_result(msg["id"], {"routes": route_data(site)})


async def save_route(hass, site, endpoint, number, user, devices, path):
    endpoint = uuid_text(endpoint)
    if user is not None:
        path = dashboard_path(path)
        number = extension(number)
        registered_users = await active_users(hass)
        registered_devices = companion_devices(hass).get(user, {})
        selected = list(dict.fromkeys(devices))
        phone = (site.inventory or {}).get("phones", {}).get(endpoint)
        if (phone is None or phone.gateway or not phone.enabled or phone.extension != number
                or user not in registered_users or len(selected) > 16
                or any(device not in registered_devices for device in selected)):
            raise ValueError("Choose an enabled extension, an active user and only their Companion devices.")
    elif devices:
        raise ValueError("No devices can be retained when removing a mapping.")

    # Do not yield between reading and updating the current entry options.
    routes = dict(site.routes)
    if user is None:
        routes.pop(endpoint, None)
    else:
        if endpoint not in routes and len(routes) >= MAX_ROUTES:
            raise ValueError("This location has reached its notification mapping limit.")
        routes[endpoint] = {"extension": number, "user_id": user, "devices": selected, "dashboard_path": path}
    hass.config_entries.async_update_entry(site.entry, options={**site.entry.options, "routes": routes})
    async_dispatcher_send(hass, site.route_signal)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/my_calls", **SITE})
@websocket_api.async_response
async def ws_my_calls(hass, connection, msg):
    site = get_site(hass, msg["site_id"])
    user = connection.user
    if site is None or not user.is_active:
        connection.send_error(msg["id"], "not_found", "No Simson site available.")
        return
    owned = {endpoint for endpoint, route in site.routes.items() if route["user_id"] == user.id}
    connection.send_result(msg["id"], {"calls": [event for event in site.live_calls() if event["endpoint_id"] in owned]})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/watch_pickup", **SITE, vol.Required("call_id"): str})
@websocket_api.async_response
async def ws_watch_pickup(hass, connection, msg):
    site = get_site(hass, msg["site_id"])
    try:
        call_id = uuid_text(msg["call_id"])
    except ValueError:
        connection.send_error(msg["id"], "invalid_format", "Invalid call ID.")
        return
    if site is None or not connection.user.is_active:
        connection.send_error(msg["id"], "not_found", "No Simson site available.")
        return
    message_id = msg["id"]
    unsubscribers = []
    timer = None
    previous = object()
    closed = False

    @callback
    def current():
        if connection.user.is_active and get_site(hass, site.site_id) is site:
            for event in site.live_calls():
                if event["call_id"] == call_id and event["state"] == "ringing":
                    route = site.routes.get(event["endpoint_id"], {})
                    if route.get("user_id") == connection.user.id and route.get("extension") == event["extension"]:
                        return {key: event[key] for key in ("call_id", "extension", "caller")}
                    break
        return None

    if current() is None:
        connection.send_result(message_id)
        connection.send_event(message_id, {"call": None})
        return
    if site.pickup_watchers >= 64:
        connection.send_error(message_id, "unavailable", "Call status is temporarily unavailable.")
        return

    @callback
    def unsubscribe():
        nonlocal closed
        if closed:
            return
        closed = True
        site.pickup_watchers -= 1
        if timer is not None:
            timer.cancel()
        for unsubscribe_signal in unsubscribers:
            unsubscribe_signal()

    @callback
    def update():
        nonlocal previous
        item = current()
        if item != previous:
            previous = item
            connection.send_event(message_id, {"call": item})
        if item is None:
            connection.subscriptions.pop(message_id, None)
            unsubscribe()

    @callback
    def expire():
        connection.send_event(message_id, {"call": None})
        if connection.subscriptions.pop(message_id, None) is not None:
            unsubscribe()

    unsubscribers.extend(async_dispatcher_connect(hass, signal, update) for signal in (site.signal, site.route_signal))
    connection.subscriptions[message_id] = unsubscribe
    site.pickup_watchers += 1
    timer = hass.loop.call_later(45, expire)
    connection.send_result(message_id)
    update()


def register(hass):
    hass.http.register_view(CallWebhook())
    for command in (ws_directory, ws_set_route, ws_my_calls, ws_watch_pickup):
        websocket_api.async_register_command(hass, command)
