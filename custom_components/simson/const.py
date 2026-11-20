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
    "extensions.manage",
    "calls.read",
    "calls.control",
)

CONF_TENANT_ID = "tenant_id"
CONF_SITE_ID = "site_id"
CONF_TENANT_NAME = "tenant_name"
CONF_SITE_NAME = "site_name"
CONF_API_BASE = "api_base"

# Polling cadence. Quiet when nothing is happening, quick during a call.
SCAN_INTERVAL_IDLE = 30
SCAN_INTERVAL_ACTIVE = 4

EVENT_INCOMING = "incoming"
EVENT_ANSWERED = "answered"
EVENT_ENDED = "ended"
EVENT_MISSED = "missed"
EVENT_TYPES = [EVENT_INCOMING, EVENT_ANSWERED, EVENT_ENDED, EVENT_MISSED]

# Fired on the Home Assistant bus for every call change, for automations.
BUS_EVENT = "simson_call_event"

SERVICE_CALL = "call"
SERVICE_HANGUP = "hangup"
SERVICE_CREATE_EXTENSION = "create_extension"
SERVICE_DELETE_EXTENSION = "delete_extension"
SERVICE_RESET_PASSWORD = "reset_extension_password"
