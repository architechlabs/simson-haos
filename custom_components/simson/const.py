"""Constants for the Simson integration."""

from __future__ import annotations

DOMAIN = "simson"

# Public endpoints of the Simson cloud. The consent screen lives on the portal,
# tokens and the API on the API host.
API_BASE = "https://api-simson.architechlabs.in"
OAUTH_AUTHORIZE_URL = "https://simson.architechlabs.in/integrations/authorize/"
OAUTH_TOKEN_URL = f"{API_BASE}/oauth/token"
CLIENT_ID = "home-assistant"

SCOPES = (
    "workspace.read",
    "calls.read",
    "calls.control",
    "automations.run",
    "events.read",
)

CONF_TENANT_ID = "tenant_id"
CONF_SITE_ID = "site_id"
CONF_TENANT_NAME = "tenant_name"
CONF_SITE_NAME = "site_name"
CONF_API_BASE = "api_base"
CONF_DEFAULT_EXTENSION = "default_extension"
CONF_BROWSER_EXTENSION = "browser_extension"
DEFAULT_BROWSER_EXTENSION = "100"
CONF_SCAN_IDLE = "scan_interval_idle"
CONF_SCAN_ACTIVE = "scan_interval_active"

# Polling cadence. Quiet when nothing is happening, quick during a call.
SCAN_INTERVAL_IDLE = 30
SCAN_INTERVAL_ACTIVE = 4
# Presets and carrier numbers rarely change: refresh them every Nth poll.
SLOW_REFRESH_EVERY = 10

EVENT_INCOMING = "incoming"
EVENT_ANSWERED = "answered"
EVENT_ENDED = "ended"
EVENT_MISSED = "missed"
EVENT_TYPES = [EVENT_INCOMING, EVENT_ANSWERED, EVENT_ENDED, EVENT_MISSED]

# Fired on the Home Assistant bus for every call change, for automations.
BUS_EVENT = "simson_call_event"
# Fired when a phone comes online, goes offline, is added or removed.
BUS_EXTENSION_EVENT = "simson_extension_event"

SERVICE_CALL = "call"
SERVICE_CALL_EXTENSION = "call_extension"
SERVICE_RUN_PRESET = "run_call_preset"
SERVICE_GET_HISTORY = "get_call_history"
SERVICE_GET_EXTENSIONS = "get_extensions"
SERVICE_GET_NUMBERS = "get_numbers"
SERVICE_GET_PRESETS = "get_call_presets"
SERVICE_HANGUP = "hangup"
