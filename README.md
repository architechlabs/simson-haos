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
| **Dashboard card** | The Simson phone has its own extension for incoming and outgoing audio or video on this screen. |
| **Blueprint** | Push a notification on incoming and missed calls. |

## Install

Requires Home Assistant 2025.4 or newer. Integration branding in **Devices & services** uses Home Assistant 2026.3 or newer.

1. Add [`architechlabs/simson-haos`](https://github.com/architechlabs/simson-haos) to HACS as a custom repository (type: Integration) and install **Simson**.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Simson**. Continue to the Simson sign-in page, approve access, then choose the workspace and location.

If Home Assistant shows an **Add application credentials** form, cancel it. In HACS, update or redownload **Simson 0.1.2** (or newer), restart Home Assistant, and retry from **Add integration**. Simson uses a built-in OAuth client with PKCE.

If a linked location shows **Failed to set up** with a listener error on 0.1.2, update or redownload **Simson 0.1.3** (or newer) in HACS and restart Home Assistant. The existing location will be loaded with its saved sign-in.

The card is added automatically. In a dashboard choose **Add card → Simson phone**, or use `type: custom:simson-card`.

## Talk from the dashboard

1. In Simson, create a dedicated SIP extension **100** at the connected location. Use a distinct extension for each screen that should ring independently. To use another number, set **Home Assistant phone extension** in the integration options.
2. Enable H.264 for that extension and the video door station if they should exchange SIP video. The location's media runtime needs its secure SIP WebSocket listener enabled.
3. Open Home Assistant over HTTPS and add **Simson phone**. The card finds the location's realm and listener. Enter the extension's SIP password on the Connect form. The password stays in the active browser session.
4. Dial **100** from a SIP phone at the location to reach the connected screen. From the card, dial an extension or routing code. For an outside number, select the assigned outbound route. For gateway routes, include the browser extension in the route's permitted callers in Simson.

**Video call** can receive H.264 directly from a SIP video door station with the local camera off. RTSP is only needed if you separately want to embed an RTSP-derived camera entity. A secure browser session, compatible H.264 offer, and usable media path are required.

The dialer, phone controls, and call video cards share the same browser extension in one tab. Use `custom:simson-dialer-card`, `custom:simson-phone-controls-card`, and `custom:simson-video-card` to lay them out independently. With several linked locations, select a location or set the same `config_entry_id` on the cards that should share a session. To keep a physical-phone relay on a dashboard, use `custom:simson-relay-card`.

Use a manual profile for a custom listener or contact list.

```yaml
type: custom:simson-browser-phone-card
browser:
  realm: office.sip.example.net
  websocket: wss://office.sip.example.net:7443
  extension: "100"
  outbound_routes:
    - {name: Office gateway, prefix: "*809"}
    - {name: WhatsApp Business, prefix: "*833"}
  keep_connected: true
  contacts:
    - {name: Front door, extension: "202", video: true}
    - {name: Reception group, extension: "*81", mode: route}
```

Use the actual dial codes configured in Simson for your extension. The media server enforces routing, caller permissions and allowed
numbers. Install the optional [Simson V2 component](browser-sip/INSTALL.md)
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
`simson.get_targets` lists extensions, groups, saved presets and outbound dial codes with their permitted source extensions.
Per-extension registration sensors expose the device and node IDs, supported codecs, video capability and last observation time.
Location sensors also expose registered extension count, outbound route count, and workspace call totals and duration.
Custom frontend cards can subscribe to the `simson:browser_call` window event.
It provides the extension, site ID, connection state, call phase, video and mute state.
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

## Build your own: handset relay controls

A small runtime loaded on Home Assistant pages lets scripts and custom dashboards start handset relay calls and observe workspace call events. The browser phone has a separate SIP session and reports its state through the `simson:browser_call` event.

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
