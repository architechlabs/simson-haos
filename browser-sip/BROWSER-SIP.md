# Simson V2 calling in Home Assistant

## Install the card

1. Extract the release ZIP into Home Assistant's configuration directory. It includes `custom_components/simson_v2/` and sample cards. Build the ZIP from source with `npm ci` and `npm run package` in `browser-sip/`. The archive appears in the repository's `dist/` directory.
2. Add `simson_v2:` to `configuration.yaml`. Restart Home Assistant through its normal configuration workflow.
3. Add the resource `/simson-v2/simson-call-card.js` as a JavaScript module in dashboard resources.
4. Add a manual card based on `example-card.yaml` or open the card picker. Replace the sample realm, WSS address and extensions with the V2 location's values. Assign every calling dashboard tab a dedicated SIP extension. Use the same location on both Home Assistant instances for direct card-to-card calls.
5. Open Home Assistant over HTTPS, enter the assigned SIP password on the card, and select **Connect**. Keep the connected card open to receive calls. Use **Disconnect** to clear the credentials held in the browser session.

The Home Assistant account connection in Simson continues to authorize the backend's Home Assistant integration. The SIP card authenticates using its own extension, so a Home Assistant login has no effect on Simson calling permissions.

## Arrange the dashboard

Add the combined `simson-v2-call-card`, or choose the dedicated dialer, contacts, controls and video cards using `example-split-cards.yaml`. Cards sharing an extension in one dashboard tab use one registration, one call and one audio playback device. The controls card presents connection and answer actions when present. The video card shows its feed wherever you place it. Other layouts fall back to an available card for controls and playback. Select the same SIP realm, extension, WebSocket and optional relay for each view you want linked.

Connect once per dashboard tab. Use distinct extensions for separate tabs, devices and Home Assistant instances that should ring independently. Set SIP identity and display name in the card editor. Add contacts and enable video per destination in the visual editor or YAML.

## Enable the V2 browser listener

The managed voice installation uses a separate optional Compose overlay, `compose.customer-voice-webrtc.yaml`, for TCP 7443. Set `wss_port: 7443` under `listener` in the operator's managed media listener JSON and set the same port under `sip.public_tls` in the control API's private presence target. For other voice installations, explicitly expose the WSS port in the media firewall or ingress and reserve it outside SIP, management and RTP ports.

Place the realm's publicly trusted combined TLS key and certificate chain in the private media certificate directory as `wss.pem`, owned by the media UID with mode `0400`. Managed certificate renewal maintains this companion file once the listener is configured. Existing `agent.pem` continues to serve native SIP TLS. The media runtime does not start an explicitly enabled WSS listener without the operator certificate.

Point the card to `wss://<location-sip-realm>:7443`. The media hostname must resolve to the media ingress that accepts TCP 7443. Use DNS-only for a direct FreeSWITCH listener. Keep the existing UDP RTP range reachable from the browser and SIP devices. WebRTC uses DTLS-SRTP on the browser leg. Physical phones use the Simson media policy for their leg. An optional `relay` card setting takes an operator provisioned TURN URL, for example `turns:turn.example.net:5349?transport=tcp`. Enter the relay's short-lived username and password when connecting.

## Audio and video

Enable H.264 on the browser extension and the VDP or other video extension. Use a browser with H.264 WebRTC support and an interoperable H.264 profile on the device. The card shows received video once the browser decodes frames. **Video call** can receive video with the local camera off. Enable **Share my camera** when you need two-way video, or choose **Answer with camera** on an incoming video call. Manual keypad tones use negotiated RTP DTMF. A doorphone can map an authorized keypad sequence to its own unlock action.

For two Home Assistant screens, configure distinct extensions and add the peer's extension to each card. Server routing checks the authenticated caller and confines ordinary extension dialing to the same location. A card can be a destination for an existing authorized route using its extension. Browser registrations are session-based. Leaving the page disconnects the phone.
