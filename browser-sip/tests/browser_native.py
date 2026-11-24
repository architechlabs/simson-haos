"""Exercise the bundled card against an isolated native SIP/WebRTC fixture."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import re
import threading

from playwright.sync_api import expect, sync_playwright

HOST = "voice.fixture.invalid"
BUNDLE = Path(__file__).resolve().parents[1] / "custom_components/simson_v2/www"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = b'<!doctype html><meta charset="utf-8"><script type="module" src="/simson-call-card.js"></script><main></main>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, format, *args):
        pass


def configure(page, origin, extension, target, layouts):
    page.goto(origin)
    page.evaluate(
        """async ([extension, target, layouts]) => {
            for (const layout of layouts) {
                const type = 'simson-v2-' + layout + '-card';
                await customElements.whenDefined(type);
                const card = document.createElement(type);
                card.setConfig({ realm: 'voice.fixture.invalid', websocket: 'wss://voice.fixture.invalid:17443',
                    extension, contacts: [{ extension: target, name: 'Test desk', video: true }] });
                document.querySelector('main').append(card);
            }
        }""",
        [extension, target, layouts],
    )
    login = page.locator("#login:visible")
    assert not page.evaluate("performance.getEntriesByType('resource').some(entry => entry.name.endsWith('/browser-phone.js'))")
    login.get_by_label("SIP password").fill("fixture_only_long_sip_password_1234567890")
    login.get_by_label("Ring for incoming calls").uncheck()
    login.get_by_role("button", name="Connect", exact=True).click()
    expect(page.locator("#state")).to_have_text(["Ready"] * len(layouts), timeout=15_000)
    assert all(field.input_value() == "" for field in page.get_by_label("SIP password").all())


def expect_media(page, *, video, local_camera=False):
    page.wait_for_function(
        """([video, localCamera]) => {
            const card = document.querySelector('simson-v2-video-card, simson-v2-call-card');
            const handler = card.phone?.call?.session.sessionDescriptionHandler;
            const peer = handler?.peerConnection;
            const tracks = handler?.localMediaStream.getVideoTracks();
            const frame = card.shadowRoot.querySelector('#remote').videoWidth;
            return peer?.connectionState === 'connected' && Boolean(tracks?.length) === localCamera && (!video || frame > 0);
        }""",
        arg=[video, local_camera],
        timeout=15_000,
    )
    page.wait_for_function(
        """async (video) => {
            const card = document.querySelector('simson-v2-video-card, simson-v2-call-card');
            const stats = await card.phone?.call?.session.sessionDescriptionHandler.peerConnection.getStats();
            const reports = Array.from(stats?.values() ?? []);
            return reports.some(r => r.type==='inbound-rtp' && r.kind==='audio' && r.packetsReceived > 4) &&
                reports.some(r => r.type==='outbound-rtp' && r.kind==='audio' && r.packetsSent > 4) &&
                (!video || reports.some(r => r.type==='inbound-rtp' && r.kind==='video' && r.framesDecoded > 2));
        }""",
        arg=video,
        timeout=15_000,
    )


def check_editor(page):
    page.evaluate("""async () => {
        const editor = await customElements.get('simson-v2-contacts-card').getConfigElement();
        editor.setConfig({ type: 'custom:simson-v2-contacts-card', realm: 'voice.fixture.invalid',
            websocket: 'wss://voice.fixture.invalid:17443', extension: '1040' });
        editor.addEventListener('config-changed', event => { window.testCardConfig = event.detail.config; });
        document.body.append(editor);
    }""")
    editor = page.locator("simson-v2-card-editor")
    editor.get_by_role("button", name="Add contact").click()
    editor.get_by_label("Name", exact=True).fill("Front door")
    editor.get_by_label("Extension", exact=True).fill("1042")
    editor.get_by_label("Video calls").check()
    editor.get_by_role("button", name="Apply card settings").click()
    assert page.evaluate("window.testCardConfig.contacts") == [{"extension": "1042", "name": "Front door", "video": True}]
    editor.evaluate("element => element.remove()")


def check_media_panel(page):
    page.evaluate("""() => {
        window.loadCardHelpers = async () => ({ createCardElement(config) {
            const panel = document.createElement('div');
            panel.textContent = `${config.type} ${config.entity}`;
            return panel;
        }});
        const card = document.createElement('simson-v2-media-card');
        card.setConfig({ realm: 'voice.fixture.invalid', websocket: 'wss://voice.fixture.invalid:17443', extension: '1040',
            camera_entity: 'camera.front_door', media_player_entity: 'media_player.front_room' });
        document.querySelector('main').append(card);
    }""")
    card = page.locator("simson-v2-media-card")
    expect(card.get_by_text("media-control media_player.front_room")).to_be_visible()
    expect(card.get_by_text("picture-entity camera.front_door")).to_have_count(0)
    card.get_by_role("button", name="Show camera").click()
    expect(card.get_by_text("picture-entity camera.front_door")).to_be_visible()
    card.get_by_role("button", name="Hide camera").click()
    expect(card.get_by_text("picture-entity camera.front_door")).to_have_count(0)
    card.evaluate("element => element.remove()")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-address", required=True)
    parser.add_argument("--fixture-cert-pin", required=True)
    parser.add_argument("--native-doorphone", action="store_true")
    parser.add_argument("--carrier-signal", type=Path)
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.fixture_address)
    if not (address.is_loopback or address.is_private and not address.is_link_local):
        raise SystemExit("The browser drill requires an isolated local fixture address.")
    if not re.fullmatch(r"[A-Za-z0-9+/]{43}=", args.fixture_cert_pin):
        raise SystemExit("Provide the disposable fixture certificate's SPKI pin.")
    handler = partial(Handler, directory=str(BUNDLE))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as first_server, ThreadingHTTPServer(("127.0.0.1", 0), handler) as second_server:
        for server in (first_server, second_server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f"http://127.0.0.1:{first_server.server_port}"
        other_origin = f"http://127.0.0.1:{second_server.server_port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=[
                f"--host-resolver-rules=MAP {HOST} {address}",
                f"--ignore-certificate-errors-spki-list={args.fixture_cert_pin}",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--disable-features=WebRtcHideLocalIpsWithMdns",
                "--allow-loopback-in-peer-connection",
            ])
            contexts = [browser.new_context(permissions=["microphone", "camera"]) for _ in range(2)]
            first, second = (context.new_page() for context in contexts)
            first.set_viewport_size({"width": 375, "height": 720})
            first_sockets = []
            first.on("websocket", lambda websocket: first_sockets.append(websocket.url))
            configure(first, origin, "1040", "1041", ["dialer", "contacts", "controls", "video"])
            controls = first.locator("simson-v2-controls-card")
            dialer = first.locator("simson-v2-dialer-card")
            dialer.get_by_label("Extension", exact=True).fill("1041")
            first.get_by_role("button", name="Audio call").click()
            expect(controls.locator("#call-phase")).to_have_text("Ringing", timeout=10_000)
            first.wait_for_timeout(1_500)
            configure(second, other_origin, "1041", "1040", ["call"])
            expect(second.locator("#call-phase")).to_have_text("Incoming call", timeout=10_000)
            second.get_by_role("button", name="Answer", exact=True).click()
            expect_media(first, video=False)
            second.get_by_role("button", name="End call").click()
            expect(dialer.locator("#dial")).to_be_visible()
            check_editor(first)
            check_media_panel(first)
            assert first.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert len(first_sockets) == 1, "The modular dashboard used more than one SIP connection."
            assert first.evaluate("""() => {
                const cards = [...document.querySelector('main').children];
                return new Set(cards.map(card => card.phone)).size === 1;
            }""")

            dialer.get_by_label("Extension", exact=True).fill("1041")
            first.get_by_role("button", name="Audio call").click()
            expect(second.locator("#call-phase")).to_have_text("Incoming call", timeout=10_000)
            second.get_by_role("button", name="Answer", exact=True).click()
            expect(controls.locator("#call-phase")).to_have_text("In call", timeout=10_000)
            expect_media(first, video=False)
            expect_media(second, video=False)
            first.get_by_role("button", name="Mute", exact=True).click()
            expect(first.get_by_role("button", name="Unmute")).to_have_attribute("aria-pressed", "true")
            first.get_by_role("button", name="End call").click()
            expect(second.locator("#dial")).to_be_visible()
            expect(dialer.locator("#dial")).to_be_visible()

            if args.native_doorphone:
                for video, label in ((False, "Audio call"), (True, "Video call")):
                    dialer.get_by_label("Extension", exact=True).fill("1042")
                    first.get_by_role("button", name=label, exact=True).click()
                    expect(controls.locator("#call-phase")).to_have_text("In call", timeout=10_000)
                    expect_media(first, video=video)
                    first.get_by_role("button", name="End call").click()
                    expect(dialer.locator("#dial")).to_be_visible()

            first.locator("simson-v2-contacts-card").get_by_role("button", name=re.compile("Test desk")).click()
            expect(second.locator("#call-phase")).to_have_text("Incoming call", timeout=10_000)
            second.get_by_role("button", name="Answer with camera", exact=True).click()
            expect_media(first, video=True)
            expect_media(second, video=False, local_camera=True)
            second.get_by_role("button", name="End call").click()
            expect(dialer.locator("#dial")).to_be_visible()

            second.get_by_label("Extension", exact=True).fill("1040")
            second.get_by_label("Share my camera on video calls").check()
            second.get_by_role("button", name="Video call", exact=True).click()
            expect(controls.locator("#call-phase")).to_have_text("Incoming call", timeout=10_000)
            first.get_by_role("button", name="Answer with camera", exact=True).click()
            expect_media(first, video=True, local_camera=True)
            expect_media(second, video=True, local_camera=True)
            first.get_by_role("button", name="End call").click()
            expect(second.locator("#dial")).to_be_visible()
            assert len(first_sockets) == 1
            for page, count in ((first, 4), (second, 1)):
                page.get_by_role("button", name="Disconnect", exact=True).click()
                expect(page.locator("#state")).to_have_text(["Disconnected"] * count)
            if args.carrier_signal:
                args.carrier_signal.touch(exist_ok=False)
                second.wait_for_timeout(1_500)
                configure(second, other_origin, "1041", "1040", ["call"])
                expect(second.locator("#call-phase")).to_have_text("Incoming call", timeout=10_000)
                second.get_by_role("button", name="Answer", exact=True).click()
                expect_media(second, video=False)
                second.get_by_role("button", name="End call").click()
                expect(second.locator("#dial")).to_be_visible()
                second.wait_for_timeout(400)
            browser.close()
        first_server.shutdown()
        second_server.shutdown()
    print("Two dashboard origins verified shared controls, audio, H.264 video, and hangup through FreeSWITCH.")
    if args.native_doorphone:
        print("The browser also verified audio and H.264 reception from a native SIP doorphone.")
    if args.carrier_signal:
        print("A synthetic carrier routed an existing call to a browser that registered after ringing began.")


if __name__ == "__main__":
    main()
