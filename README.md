# Simson for Home Assistant

Call between the phones at a Simson location, see who is online, react to calls in
automations, and add phones, all from Home Assistant. There is no add-on to
install: Home Assistant signs in to Simson with OAuth and talks to the Simson
cloud directly.

## What you get

| | |
|---|---|
| **Sign in** | One click. Home Assistant opens Simson, you approve exactly what it may do, and it comes back signed in. No passwords or tokens to paste. Tokens refresh themselves and you can revoke the connection from the Simson dashboard at any time. |
| **Phones** | A `Registered` sensor for every SIP phone and gateway, grouped under one device per location. |
| **Calls** | `simson.call` rings two phones and connects them. Audio goes phone to phone over the voice service, so there is no browser handshake to wait for. |
| **Events** | An event entity fires `incoming`, `answered`, `ended` and `missed`. The same events go on the bus as `simson_call_event`. |
| **Phones from Home Assistant** | `simson.create_extension`, `simson.reset_extension_password` and `simson.delete_extension`. The new password arrives sealed and is shown once. |
| **Dashboard card** | `Simson` card: pick a phone, dial, hang up, add a phone. |
| **Blueprint** | Push a notification on incoming and missed calls. |

## Install

1. Add this repository to HACS as a custom repository (type: Integration) and install **Simson**.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Simson**, sign in, then choose the workspace and location.

The card is added automatically. In a dashboard choose **Add card → Simson**, or use `type: custom:simson-card`.

## Services

```yaml
action: simson.call
data:
  from_extension: "1201"
  to_extension: "1202"
```

```yaml
action: simson.create_extension
data:
  name: Kitchen
  extension: "1204"
```

`simson.call` and `simson.create_extension` return data you can use in scripts
(`response_variable`). Calls to outside numbers through a carrier gateway are placed
from the Simson dashboard for now.

## Permissions

The connection asks for four scopes and shows them on the consent screen:

| Scope | Lets Home Assistant |
|---|---|
| `workspace.read` | See locations, phones and who is online |
| `extensions.manage` | Create, change and remove phones and reset their passwords |
| `calls.read` | Read call history and active calls |
| `calls.control` | Start and end calls |

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
`simson-live-call-card` and `simson-add-phone-card`. Each can be placed alone.

## Why the card no longer shows "Configuration error"

`simson-card.js` is a tiny file that defines the card elements the instant it runs,
so Home Assistant always finds them. The interface loads in the background and
replaces the placeholder as soon as it is ready. The files are versioned and cached.

## Development

```
python -m pytest
```

The API client, the one-time credential decryption (tested against a credential
sealed by the Simson server) and the call-event logic are independent of Home
Assistant and covered by tests. The card is checked in a real browser.
