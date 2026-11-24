# Simson V2 Home Assistant setup

## Install and sign in

1. Extract the release ZIP into Home Assistant's configuration directory. The complete `custom_components/simson_v2` directory includes the compiled card bundle.
2. Add `/simson-v2/simson-call-card.js` to dashboard resources as a JavaScript module.
3. For account linking and notifications, provide the Home Assistant Core process with a Fernet key at `/share/simson-v2-private/oauth.key`. Use a private directory and mode `0400` for the file. Keep this directory out of unencrypted backups. The encryption key is separate from the configuration and the encrypted refresh token.
4. In Home Assistant, open **Settings → Devices & services → Add integration → Simson V2**. Open the Simson sign-in prompt, approve **See your workspace** and **Receive live call events**, then return through My Home Assistant. Choose a workspace you administer and its Simson location.
5. In the Simson portal, open that location's **Integrations → Home Assistant** panel. Authorize the instance with a Home Assistant administrator to enable the portal directory. Set a call notification assignment using the existing SIP extension, its Home Assistant user, that user's registered Companion phones and a local dashboard path such as `/lovelace/calls`.

Home Assistant 2026.3 and newer display the bundled Simson branding in Devices & services. All six dashboard layouts have a branded preview in the card picker. Open the card editor to enter location and extension settings before connecting.

Card-only installations can continue using `simson_v2:` in `configuration.yaml` and skip account linking. Use different SIP extensions for different devices or Home Assistant instances. The card asks for the SIP password on Connect, and the registration remains active while its dashboard is open.

Add one Simson config entry for each location you want on this Home Assistant installation. Each entry has its own scoped stream checkpoint, extension devices, assignments and state. The cloud feed reconnects automatically and runs while all dashboards are closed. Enable **Keep SIP connected between dashboard views** on a call card to retain its registration in that tab. Closing the browser or suspending the tab can end that registration. Companion notifications continue through the integration while Home Assistant stays online.

## Calls and notifications

- Route to the assigned SIP extension using the location's existing call routing or automation. The assignment selects the Companion notification destination for a ringing event. It does not change the SIP dialplan.
- The server streams site-scoped lifecycle events for persisted call intents. Older revisions, terminal replays, unrelated locations and unmapped endpoints are skipped. Notification routing uses the immutable endpoint ID and the device's current Home Assistant user registration.
- The notification opens the assigned HA dashboard. Add `site_id` to the call card to match its notification link. Standard **Answer** and **Decline** on the card act on its current SIP invitation. Open the notification before the pickup window closes. Phones and browsers already registered can answer at once.
- Opt in a dedicated browser extension by setting its immutable endpoint UUID in the media listener's `browser_pickup_endpoints` list. A direct SIP call or a single-target carrier or SIP routing stage can send a native ringing notification. When the destination has no registration the caller hears normal ringing while the media runtime waits up to 24 seconds for registration. The port needs valid SIP WSS and the call worker needs `CALL_BROWSER_PICKUP_ENABLED=yes` alongside call events.
- When the assigned user opens the notification, the card verifies the offer with Home Assistant over its authenticated WebSocket. Connect using the extension's SIP password and answer or decline the real invitation. The card loads its phone bundle while the user enters the password. An unassigned user sees no caller details.
- Parallel multi-phone stages and worker-based call intents keep their existing routing and timeouts. An operator-controlled event producer can also publish state to the authenticated Home Assistant endpoint described in the included local OpenAPI contract.

## Use Home Assistant automations and entities

Each site appears as a Home Assistant device. SIP extensions and gateways appear under it automatically after inventory loads, with stable entity IDs. Use native automation triggers and conditions on the following entities.

| Device | Entities |
| --- | --- |
| Site | Cloud connection, presence health and last successful check, reachable and configured media servers, enabled groups, configured extensions and gateways, and registration totals by state |
| Site | Ringing and active call conditions, live and ringing call counts, last call event and time, observed answers and missed calls, and last automation dispatch |
| Extension or gateway | Registration, ringing and in-call conditions, extension number, phone group, provisioning status, video capability and whether SIP credentials were configured |
| Mapped extension | Companion contact status and selected phone count |
| Site controls | Refresh presence button, Companion notification switch and scoped automation buttons |
| Site events | Call lifecycle, extension registration transitions, automation dispatch and Companion notification requests or errors |

If registrar data is stale or unreachable, the extension reports unknown and the registered binary sensor becomes unavailable. Treat confirmed `offline` separately from missing data. Call counters measure targeted call events observed by this integration since installation. They are unsuitable for billing or complete call history.

Home Assistant event automations can still listen for `simson_v2_call`, `simson_v2_registration`, `simson_v2_automation` and `simson_v2_notification`. Filter by `site_id` and `endpoint_id` whenever an action controls a site or extension. Call events include the call or route-attempt ID, state and revision. Set `replayed: false` in the trigger for actions that should only run on new transitions. For actions that may repeat after a crash, use the call ID and revision to deduplicate downstream.

For example, this automation turns on an entry light when the doorphone first rings. Replace the sample IDs with the location and extension IDs from Simson.

```yaml
alias: Turn on entry light for doorphone calls
triggers:
  - trigger: event
    event_type: simson_v2_call
    event_data:
      site_id: "11111111-1111-4111-8111-111111111111"
      endpoint_id: "22222222-2222-4222-8222-222222222222"
      state: ringing
      replayed: false
actions:
  - action: light.turn_on
    target:
      entity_id: light.entry
mode: single
```

The `requested` and `clear_requested` mobile events mean Home Assistant accepted the corresponding Companion service call. Device receipt depends on Companion and the phone's connection.

To trigger a saved Simson automation, create its scoped webhook credential in the Simson portal. Install the token in a mode-`0400` file at `/share/simson-v2-private/<site-id>/<automation-name>.key`. Use a lower-case name containing letters, digits, underscores or hyphens. The key can run only the saved automation on which it was issued. The integration loads one native button per installed key during setup. Use the `simson_v2.trigger_automation` action from Home Assistant with the site ID and key name. The optional event UUID and occurrence timestamp must be supplied together and reused on retry. A queued result means the backend accepted the intent.

## Separate door and room media

Use a configured 2N or other video doorphone as a normal SIP extension. Native SIP video is H.264. For a separate local RTSP feed, configure the vendor's camera integration, a Home Assistant camera entity backed by a local bridge, or an RTSP-capable camera integration. Keep the source URL and device credentials on that local system.

The combined, Video and Door and room media cards accept `camera_entity`, `media_player_entity` and optional `media_extension`. Choose the doorphone extension to show that camera while its SIP call is open. The media card also supports manual preview. Home Assistant's own browser session checks access to these entities and streams the camera through its native player. Control room audio on a separate Home Assistant media player, or target it from Home Assistant actions. The independent player does not replace SIP two-way audio.

The ZIP includes standalone, split and external-media layouts. Configure WSS on the V2 media listener before making calls. Read the included browser SIP notes for TLS, DNS and codec requirements.
