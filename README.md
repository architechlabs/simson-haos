# Simson for Home Assistant

Call between the phones at a Simson location, see who is online, react to calls in
automations and see status for existing phones, all from Home Assistant. There is no add-on to
install: Home Assistant signs in to Simson with OAuth and talks to the Simson
cloud directly.

## What you get

| | |
|---|---|
| **Sign in** | One click. Home Assistant opens Simson, you approve exactly what it may do, and it comes back signed in. No passwords or tokens to paste. Tokens refresh themselves and you can revoke the connection from the Simson dashboard at any time. |
| **Phones** | A `Registered` sensor for every SIP phone and gateway, grouped under one device per location. |
| **Calls** | `simson.call` rings two phones and connects them. Audio goes phone to phone over the voice service, so there is no browser handshake to wait for. |
| **Events** | An event entity fires `incoming`, `answered`, `ended` and `missed`. The same events go on the bus as `simson_call_event`. |
| **Dashboard card** | `Simson` rings physical phones. `Simson browser phone` supports direct microphone and video calls on this device. |
| **Blueprint** | Push a notification on incoming and missed calls. |

## Install

Requires Home Assistant 2025.4 or newer. Integration branding in **Devices & services** uses Home Assistant 2026.3 or newer.

1. Add [`architechlabs/simson-haos`](https://github.com/architechlabs/simson-haos) to HACS as a custom repository (type: Integration) and install **Simson**.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Simson**. Continue to the Simson sign-in page, approve access, then choose the workspace and location.

If Home Assistant shows an **Add application credentials** form, cancel it. In HACS, update or redownload **Simson 0.1.2** (or newer), restart Home Assistant, and retry from **Add integration**. Simson uses a built-in OAuth client with PKCE.

If a linked location shows **Failed to set up** with a listener error on 0.1.2, update or redownload **Simson 0.1.3** (or newer) in HACS and restart Home Assistant. The existing location will be loaded with its saved sign-in.

The card is added automatically. In a dashboard choose **Add card → Simson**, or use `type: custom:simson-card`.

## Talk from the dashboard

The Simson card includes the browser phone. Use Home Assistant over HTTPS and a dedicated, existing browser SIP extension
with a matching SIP realm and WSS address. Enter its SIP password through
the card's **Connect** form. Card configuration stores only connection details.

```yaml
type: custom:simson-browser-phone-card
browser:
  realm: office.sip.example.net
  websocket: wss://office.sip.example.net:7443
  extension: "203"
  gateway_prefix: "*9"
  keep_connected: true
  contacts:
    - {name: Front door, extension: "202", video: true}
    - {name: Reception group, extension: "*81", mode: route}
```

Remove the example carrier prefix unless it matches the outbound route configured
in Simson for this extension. **SIP phone** calls an extension, **Node or route**
dials a route code configured in Simson, and **Outside** uses the configured
carrier prefix. The media server enforces routing, caller permissions and allowed
numbers. Separate browser layouts are available for dialing, contacts, controls,
video, and a local camera or media player. Install the optional [Simson V2 component](browser-sip/INSTALL.md)
for Companion notifications and site entities. Its phone assignment is under
**Settings → Devices & services → Simson V2 → Configure**.

## Services

```yaml
action: simson.call
data:
  from_extension: "1201"
  to_extension: "1202"
```

That action rings the source handset and connects it to the destination.
`simson.get_targets` lists extensions, groups and saved presets for scripts.
Provision, enable, and reset extensions from the Simson portal.

## Permissions

The connection shows these scopes on the consent screen:

| Scope | Lets Home Assistant |
|---|---|
| `workspace.read` | See locations, phones and who is online |
| `calls.read` | Read call history and active calls |
| `calls.control` | Start and end calls |
| `automations.run` | List and run saved call presets |
| `events.read` | Receive live call events |

Home Assistant acts as you: it can never do more than your Simson role allows.

## Build your own: the call layer

The calling experience does not live in a card. A small runtime is loaded on every
Home Assistant page, so a call rings, can be ended and shows its state on whatever
dashboard, panel or custom page you are looking at. Cards, scripts and your own
dashboards only trigger it.

```js
window.simson.call("1201", "1202");                 // place a call
window.simson.call("1201", "1202", { video: true }); // video call
window.simson.hangup(callId);
window.simson.on("incoming", (call) => console.log(call));  // also: answered, ended, missed
window.simson.configure({ overlay: false });        // hide the built-in overlay, keep the events
window.simson.mount(element);                       // render the live-call view anywhere
window.simson.registerTransport(myTransport);       // plug in browser audio and video
```

The same events are DOM events on `window` (`simson:incoming`, `simson:answered`,
`simson:ended`, `simson:missed`, `simson:media`) and Home Assistant bus events
(`simson_call_event`), so a button-card, a script or an automation can react without
any JavaScript.

**Microphone and camera.** When a call is placed through a transport that uses the
browser for audio, the browser asks for the microphone (and the camera for a video
call) at the same moment the call is placed, in parallel with setting it up. Nothing
waits for the connection first. The default transport rings the two phones and
connects them, so it needs no browser audio and asks for nothing.

**Cards.** `simson-card` (everything), `simson-dialer-card`, `simson-phones-card`,
`simson-live-call-card`, `simson-history-card` and `simson-browser-phone-card`. Each can be placed alone.

## Why the card no longer shows "Configuration error"

Simson registers its dashboard resource automatically. If you migrated from V1,
remove the old `/simson/www/simson-card.js?v=5.9.5` entry under **Settings → Dashboards → Resources**.
The current card interface and its assets are served from a release-specific URL.
Cards can retry a failed load in place when the app reconnects or returns to the foreground.

## Development

```
python -m pytest
```

The API client, the one-time credential decryption (tested against a credential
sealed by the Simson server) and the call-event logic are independent of Home
Assistant and covered by tests. The card is checked in a real browser.

## Live events

Incoming, answered, ended and missed calls arrive the moment they happen over a
private event stream, not on the next refresh. Each one fires the `simson_call_event`
bus event and the **Calls** event entity, now with who is calling:

```yaml
trigger:
  - platform: event
    event_type: simson_call_event
    event_data: {event: incoming}
action:
  - service: notify.notify
    data:
      message: "{{ trigger.event.data.caller_name or 'Someone' }} is calling {{ trigger.event.data.callee_name or 'a phone' }}"
```

`caller_*` and `callee_*` are filled for calls started from Simson. Calls that
come from outside carry `null` for both. When the stream drops, the integration
reconnects and requests available events after its last cursor. Normal refreshing
continues to check call state while the stream is unavailable. Connections
made before this feature need **Reconfigure / sign in again** once to grant
the new "live call events" permission.
