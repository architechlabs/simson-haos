"""The cards and the global call layer in a real browser, against a fake Home Assistant."""

import functools
import http.server
import pathlib
import re
import threading

import pytest

playwright = pytest.importorskip("playwright.sync_api")

WWW = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "simson" / "www"

HARNESS = """<!doctype html><meta charset=utf-8><body>
<home-assistant id="ha"></home-assistant>
<script type="module">
  const subs = {};
  const state = (entity_id, value, attributes) => ({ entity_id, state: value, attributes });
  window.calls = [];
  window.hass = {
    states: {
      "binary_sensor.kitchen": state("binary_sensor.kitchen", "on", { simson_extension: "1201", name: "Kitchen", enabled: true, gateway: false }),
      "binary_sensor.hall": state("binary_sensor.hall", "off", { simson_extension: "1202", name: "Hall", enabled: true, gateway: false }),
      "binary_sensor.sim": state("binary_sensor.sim", "unknown", { simson_extension: "1701", name: "SIM", enabled: true, gateway: true }),
      "sensor.active": state("sensor.active", "0", { simson_calls: true, calls: [] }),
    },
    connection: { subscribeEvents: async (callback, type) => { (subs[type] ||= []).push(callback); return () => {}; } },
    callService: async (domain, service, data) => { window.calls.push([domain, service, data]); if (window.failCalls) throw new Error("Extension 1202 is turned off."); },
    callWS: async (message) => {
      window.calls.push(["ws", message]);
      if (window.failCalls) throw new Error("Extension 1202 is turned off.");
      if (message.service === "get_call_history") return { response: { calls: [{ phase: "ended", started_at: "2026-11-20T10:00:00Z", answered: true, duration_seconds: 42 }] } };
      return { response: { call_id: "new-call", state: "queued" } };
    },
  };
  document.getElementById("ha").hass = window.hass;
  window.__subs = subs;
  window.pushCalls = (calls) => {
    window.hass.states["sensor.active"] = state("sensor.active", String(calls.length), { simson_calls: true, calls });
    (subs.state_changed || []).forEach((cb) => cb({ data: { entity_id: "sensor.active" } }));
  };
  window.pushBus = (data) => (subs.simson_call_event || []).forEach((cb) => cb({ data }));
  window.heard = [];
  import("/simson-card.js").then(() => {
    window.definedAtLoad = ["simson-card", "simson-relay-card", "simson-dialer-card", "simson-phones-card", "simson-live-call-card", "simson-add-phone-card"].every((name) => !!customElements.get(name));
    for (const type of ["incoming", "answered", "ended", "missed"]) window.simson.on(type, (call) => window.heard.push([type, call.id]));
    const params = new URLSearchParams(location.search);
    for (const tag of (params.get("cards") || "").split(",").filter(Boolean)) {
      const card = document.createElement(tag);
      card.setConfig(params.get("relay") === "1" ? { mode: "relay" } : {});
      document.body.append(card);
      card.hass = window.hass;
    }
    window.initialCardText = document.querySelector("simson-card")?.shadowRoot.textContent;
    window.ready = true;
  });
</script>"""

MEDIA_STUB = """
window.media = { requests: [] };
const track = (kind) => ({ kind, enabled: true, stop() { this.stopped = true; } });
navigator.mediaDevices.getUserMedia = async (constraints) => {
  window.media.requests.push({ constraints, at: performance.now() });
  if (window.media.deny) { const error = new Error("denied"); error.name = "NotAllowedError"; throw error; }
  const tracks = [track("audio"), ...(constraints.video ? [track("video")] : [])];
  return { getTracks: () => tracks, getAudioTracks: () => tracks.filter((t) => t.kind === "audio"), getVideoTracks: () => tracks.filter((t) => t.kind === "video") };
};
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript"}

    def do_GET(self):
        if self.path.startswith("/harness.html"):
            body = HARNESS.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(WWW)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def page():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 420, "height": 800})
        page = context.new_page()
        page.errors = []
        page.on("pageerror", lambda error: page.errors.append(str(error)))
        page.on("console", lambda message: page.errors.append(message.text) if message.type == "error" else None)
        page.add_init_script(MEDIA_STUB)
        yield page
        browser.close()


def open_page(page, url, cards="simson-card", *, relay=True):
    page.goto(f"{url}/harness.html?cards={cards}&relay={int(relay)}")
    page.wait_for_function("window.ready === true")
    page.wait_for_function("window.__subs && window.__subs.simson_call_event")


def impl_ready(page, tag="simson-card"):
    page.wait_for_function("(tag) => { const host = document.querySelector(tag); return host && host.shadowRoot.querySelector('simson-card-impl'); }", arg=tag, polling=50)
    return page.locator(f"{tag} >> simson-card-impl")


def shadow_text(locator):
    return locator.evaluate("(node) => node.shadowRoot.textContent")


def overlay(page):
    return page.locator("simson-call-view")


def test_every_card_is_defined_immediately_before_the_interface_loads(site, page):
    page.goto(f"{site}/harness.html?cards=simson-card&relay=1")
    page.wait_for_function("window.ready === true")
    assert page.evaluate("window.definedAtLoad") is True, "the card elements must exist as soon as the entry script runs"
    assert "Opening Simson" in page.evaluate("window.initialCardText")
    impl_ready(page)
    assert "Kitchen" in page.locator("simson-card").evaluate("(host) => host.shadowRoot.querySelector('simson-card-impl').shadowRoot.textContent")
    assert not page.errors, page.errors


def test_picker_previews_have_branding_without_mounting_the_call_interface(site, page):
    open_page(page, site, cards="")
    visible_cards = page.evaluate("""() => {
      const picker = document.createElement('div');
      picker.inert = true;
      document.body.append(picker);
      const types = window.customCards.filter((card) => card.preview).map((card) => card.type);
      for (const type of types) {
        const card = document.createElement(type);
        card.setConfig(customElements.get(type).getStubConfig());
        card.hass = window.hass;
        picker.append(card);
      }
      return types;
    }""")
    assert len(visible_cards) == 8
    assert page.locator(".simson-preview").count() == 8
    assert page.locator("simson-card-impl").count() == 0
    assert page.get_by_alt_text("Simson by Architech Labs").count() == 8
    assert len(set(page.locator(".simson-preview ha-icon").evaluate_all("icons => icons.map(icon => icon.getAttribute('icon'))"))) == 8
    assert page.evaluate("window.calls.length") == 0
    assert page.evaluate("window.media.requests.length") == 0
    assert not page.errors, page.errors


def test_module_failures_recover_on_mobile_without_reloading(site, page):
    page.set_viewport_size({"width": 375, "height": 720})
    page.add_init_script("Storage.prototype.getItem = () => { throw new DOMException('blocked', 'SecurityError'); };")
    attempts = {"core": [], "runtime": []}
    broken = True

    def handle(module):
        def route_module(route):
            attempts[module].append(route.request.url)
            if broken:
                route.fulfill(status=503, content_type="text/plain", body="Temporary fixture failure")
            else:
                route.continue_()
        return route_module

    page.route("**/simson-card-core.js*", handle("core"))
    page.route("**/simson-runtime.js*", handle("runtime"))
    page.goto(f"{site}/harness.html?cards=simson-card&relay=1")
    retry = page.get_by_role("button", name="Retry")
    retry.wait_for()
    # Allow the scheduled retry to recover without requiring a tap or a reload.
    broken = False
    card = impl_ready(page)
    assert card.get_by_label("Extension to call").is_visible()
    page.wait_for_function("window.__subs.simson_call_event?.length === 1")
    assert all(len(set(urls)) >= 2 and any("retry=" in url for url in urls) for urls in attempts.values())


def test_existing_history_card_uses_the_read_only_history_action(site, page):
    open_page(page, site, cards="simson-history-card")
    card = impl_ready(page, "simson-history-card")
    card.get_by_role("button", name="Load recent calls").click()
    card.get_by_text("Answered · 42s").wait_for()
    assert page.evaluate("window.calls.map(entry => entry[1]?.service)") == ["get_call_history"]
    assert not page.errors, page.errors


def test_lists_phones_with_status_and_disables_gateways(site, page):
    open_page(page, site)
    inner = impl_ready(page)
    assert inner.locator(".phone").count() == 3
    assert inner.locator(".phone .dot.on").count() == 1 and inner.locator(".phone .dot.off").count() == 1
    assert inner.locator(".phone[disabled]").count() == 1
    assert "1 online" in inner.locator(".pill").text_content()
    assert not page.errors, page.errors


def test_the_phone_transport_does_not_ask_for_the_microphone(site, page):
    open_page(page, site)
    inner = impl_ready(page)
    inner.get_by_label("Extension to call").fill("1202")
    inner.get_by_role("button", name="Ring phones", exact=True).click()
    page.wait_for_function("window.calls.length === 1")
    message = page.evaluate("window.calls[0]")
    assert message[0] == "ws" and message[1]["service"] == "call" and message[1]["service_data"] == {"from_extension": "1201", "to_extension": "1202"}
    assert page.evaluate("window.media.requests.length") == 0, "phone to phone calls need no browser microphone"
    assert not page.errors, page.errors


def test_a_media_transport_asks_for_permission_the_moment_call_is_pressed(site, page):
    open_page(page, site)
    page.evaluate("""() => {
      window.transportCalledAt = null;
      window.simson.registerTransport({ name: "browser", media: true,
        call: async () => { window.transportCalledAt = performance.now(); await new Promise((r) => setTimeout(r, 1200)); return { response: { call_id: "b1" } }; },
        hangup: async () => {} });
    }""")
    inner = impl_ready(page)
    inner.get_by_label("Extension to call").fill("1202")
    inner.get_by_role("button", name="Video").click()
    page.wait_for_function("window.media.requests.length === 1", timeout=500)
    request = page.evaluate("window.media.requests[0]")
    assert request["constraints"]["video"], "a video call must ask for the camera as well"
    assert request["constraints"]["audio"]
    assert page.evaluate("window.transportCalledAt") is None or page.evaluate("window.transportCalledAt - window.media.requests[0].at < 100"), "the call must not wait for the permission answer"


def test_a_blocked_microphone_shows_a_clear_message(site, page):
    open_page(page, site)
    page.evaluate("""() => { window.media.deny = true; window.simson.registerTransport({ name: "browser", media: true, call: async () => ({}), hangup: async () => {} }); }""")
    page.evaluate("window.simson.call('1201', '1202')")
    page.evaluate("window.pushCalls([{ id: 'c1', phase: 'ringing', started_at: new Date().toISOString() }])")
    notice = overlay(page).get_by_role("alert").first
    notice.wait_for()
    assert "blocked" in notice.text_content()


def test_an_incoming_call_appears_on_any_page_without_a_card(site, page):
    open_page(page, site, cards="")
    assert page.locator("simson-card").count() == 0
    page.evaluate("window.pushCalls([{ id: 'c1', phase: 'ringing', started_at: new Date().toISOString() }])")
    dialog = overlay(page).get_by_role("dialog")
    dialog.wait_for()
    assert "Incoming call" in dialog.text_content() and "Answer on your phone" in dialog.text_content()
    assert page.evaluate("window.heard") == [["incoming", "c1"]]
    page.evaluate("window.pushCalls([{ id: 'c1', phase: 'active', started_at: new Date().toISOString(), connected_at: new Date().toISOString() }])")
    overlay(page).get_by_text("In call").wait_for()
    assert page.evaluate("window.heard")[-1] == ["answered", "c1"]
    overlay(page).get_by_role("button", name="Hang up").click()
    page.wait_for_function("window.calls.some((c) => c[1] === 'hangup')")
    assert page.evaluate("window.calls.find((c) => c[1] === 'hangup')") == ["simson", "hangup", {"call_id": "c1"}]
    page.evaluate("window.pushCalls([]); window.pushBus({ event: 'ended', call_id: 'c1', connected_seconds: 12 })")
    page.wait_for_function("document.querySelectorAll('simson-call-view').length === 0")
    assert page.evaluate("window.heard")[-1] == ["ended", "c1"]
    assert not page.errors, page.errors


def test_developers_can_turn_the_overlay_off_and_still_get_events(site, page):
    open_page(page, site, cards="")
    page.evaluate("window.simson.configure({ overlay: false })")
    page.evaluate("window.pushCalls([{ id: 'c2', phase: 'ringing', started_at: new Date().toISOString() }])")
    page.wait_for_function("window.heard.length === 1")
    assert overlay(page).count() == 0
    assert page.evaluate("window.simson.calls.length") == 1
    page.evaluate("window.simson.configure({ overlay: true })")
    overlay(page).get_by_role("dialog").wait_for()


def test_the_live_call_view_can_be_mounted_in_a_custom_dashboard(site, page):
    open_page(page, site, cards="simson-live-call-card")
    page.evaluate("window.simson.configure({ overlay: false })")
    inner = impl_ready(page, "simson-live-call-card")
    assert "No call in progress" in page.locator("simson-live-call-card simson-call-view").evaluate("(view) => view.shadowRoot.textContent")
    page.evaluate("window.pushCalls([{ id: 'c3', phase: 'active', started_at: new Date().toISOString(), connected_at: new Date().toISOString() }])")
    page.locator("simson-live-call-card simson-call-view").get_by_text("In call").wait_for()
    assert inner.count() == 1


def test_focused_cards_render_only_their_part(site, page):
    open_page(page, site, cards="simson-dialer-card,simson-phones-card")
    dialer = impl_ready(page, "simson-dialer-card")
    phones = impl_ready(page, "simson-phones-card")
    assert dialer.get_by_label("Extension to call").count() == 1 and dialer.locator(".phone").count() == 0
    assert phones.locator(".phone").count() == 2 and phones.get_by_label("Extension to call").count() == 0


def test_service_errors_are_shown_to_the_user(site, page):
    open_page(page, site)
    inner = impl_ready(page)
    page.evaluate("window.failCalls = true")
    inner.get_by_label("Extension to call").fill("1202")
    inner.get_by_role("button", name="Ring phones", exact=True).click()
    inner.get_by_role("alert").wait_for()
    assert "turned off" in inner.get_by_role("alert").text_content()


def test_phone_cards_never_offer_provisioning(site, page):
    open_page(page, site, cards="simson-card,simson-add-phone-card")
    combined = impl_ready(page)
    old_setup = impl_ready(page, "simson-add-phone-card")
    old_setup.get_by_text("Manage SIP extensions in the Simson portal.").wait_for()
    assert combined.get_by_role("button", name="Add a phone").count() == 0
    assert page.evaluate("window.customCards.some(card => card.type === 'simson-add-phone-card')") is False
    assert page.evaluate("window.calls") == []


def test_browser_phone_embeds_existing_transport_and_preserves_it_on_ha_updates(site, page):
    open_page(page, site, cards="")
    page.route("**/browser-sip/simson-call-card.js", lambda route: route.fulfill(
        status=200, content_type="text/javascript", body="""
        customElements.define("simson-v2-call-card", class extends HTMLElement {
          setConfig(value) { this.textContent = "Browser extension " + value.extension; }
        });
    """))
    page.evaluate("""() => {
        const card = document.createElement("simson-browser-phone-card");
        card.setConfig({ browser: { realm: "sip.example.net", websocket: "wss://sip.example.net:7443", extension: "1201" } });
        document.body.append(card);
        card.hass = window.hass;
    }""")
    browser_phone = impl_ready(page, "simson-browser-phone-card")
    browser_phone.get_by_text("Browser extension 1201").wait_for()
    assert browser_phone.locator("simson-v2-call-card").evaluate("""(child) => {
        const parent = document.querySelector("simson-browser-phone-card");
        parent.hass = { ...window.hass };
        return child.isConnected && child.hass !== window.hass;
    }""")
    assert page.evaluate("window.calls") == []


@pytest.mark.parametrize("tag", ["simson-card", "simson-relay-card"])
def test_default_card_discovers_its_own_extension_and_never_rings_a_source_handset(site, page, tag):
    page.set_viewport_size({"width": 320, "height": 720})
    open_page(page, site, cards=tag, relay=False)
    card = impl_ready(page, tag)
    card.get_by_text("Connect a Simson location", exact=False).wait_for()
    page.evaluate("""(tag) => {
      const host = document.querySelector(tag);
      const attributes = { simson_voice: true, config_entry_id: "office", site_name: "Office",
        browser_extension: "100", browser_endpoint_ready: true, browser_video: true,
        sip_realm: "sip.example.net", sip_wss_port: 7443, outbound_routes: [{ name: "WhatsApp Business", prefix: "*833" }] };
      const states = { ...window.hass.states, "sensor.office_voice": { attributes } };
      states["binary_sensor.kitchen"] = { ...states["binary_sensor.kitchen"], attributes: {
        ...states["binary_sensor.kitchen"].attributes, config_entry_id: "office", video: true } };
      host.hass = { ...window.hass, states };
    }""", tag)
    phone = card.locator("simson-v2-call-card")
    phone.get_by_text("Extension 100", exact=True).wait_for()
    assert phone.get_by_text("Dial 100 from another Simson phone", exact=False).is_visible()
    assert phone.evaluate("(card) => card.config.websocket") == "wss://sip.example.net:7443/"
    assert phone.locator("#destinations option").evaluate_all("options => options.map(option => option.value)") == ["1201"]
    assert phone.locator("#outbound-route option").evaluate_all("options => options.map(option => option.value)") == ["*833"]
    assert card.get_by_label("Call from", exact=True).count() == 0
    assert page.evaluate("window.calls.length") == 0
    assert not page.errors, page.errors


def test_legacy_card_keeps_an_explicit_handset_relay_mode(site, page):
    open_page(page, site, cards="simson-relay-card", relay=True)
    card = impl_ready(page, "simson-relay-card")
    assert card.get_by_label("Call from", exact=True).is_visible()


def test_phone_setup_stays_in_home_assistant_and_preserves_dashboard_path(site, page):
    page.add_init_script("Object.defineProperty(window, 'isSecureContext', { value: false });")
    open_page(page, site, relay=False)
    card = impl_ready(page)
    page.evaluate("""() => {
      const host = document.querySelector("simson-card");
      const location = { simson_voice: true, config_entry_id: "office", browser_extension: "100",
        browser_endpoint_ready: false, home_assistant_https_url: "https://home.fixture.invalid/?secret=unused" };
      const states = marker => ({ ...window.hass.states, "sensor.office_voice": { attributes: marker } });
      window.updateBrowserSetup = (overrides, admin) =>
        host.hass = { ...window.hass, user: { is_admin: admin }, states: states({ ...location, ...overrides }) };
      window.updateBrowserSetup({}, true);
    }""")
    assert card.get_by_role("link", name="Simson integration settings").get_attribute("href") == "/config/integrations/integration/simson"
    assert card.get_by_role("link", name="Open this dashboard securely").get_attribute("href") == "https://home.fixture.invalid/harness.html"
    assert card.get_by_text("waiting for an administrator", exact=False).is_visible()
    assert card.locator("a[href*='architechlabs']").count() == 0
    page.evaluate("window.updateBrowserSetup({browser_endpoint_ready:true, sip_realm:'voice.fixture.invalid', sip_wss_port:7443}, false)")
    card.get_by_text("Use this dashboard’s secure address", exact=False).wait_for()
    assert card.get_by_role("link", name="Simson integration settings").count() == 0
    assert card.get_by_label("SIP password", exact=True).count() == 0


def test_a_failed_download_shows_a_retry_message_not_a_configuration_error(site, page):
    page.route("**/simson-card-core.js*", lambda route: route.fulfill(status=500, body="nope"))
    page.goto(f"{site}/harness.html?cards=simson-card")
    page.wait_for_function("window.ready === true")
    page.get_by_role("button", name="Retry").wait_for(timeout=6000)
    assert "Configuration error" not in page.locator("simson-card").evaluate("(host) => host.shadowRoot.textContent")


def test_live_browser_dialer_sends_only_same_realm_route_and_outside_invites(site):
    realms = "voice.fixture.invalid"
    invites = []
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        context = browser.new_context(permissions=["microphone", "camera"], viewport={"width": 320, "height": 720})
        page = context.new_page()

        def sip(ws):
            def receive(message):
                first, *headers = message.split("\r\n")
                if first.startswith("INVITE "):
                    invites.append(first.split(" ")[1])
                    status = "486 Busy Here"
                elif first.startswith("REGISTER "):
                    status = "200 OK"
                else:
                    return
                rows = [f"SIP/2.0 {status}"]
                for name in ("Via", "From", "To", "Call-ID", "CSeq", "Contact"):
                    value = next((line for line in headers if line.lower().startswith(name.lower() + ":")), None)
                    if value:
                        rows.append(value + (";tag=simson-fixture" if name == "To" and ";tag=" not in value else ""))
                ws.send("\r\n".join([*rows, "Content-Length: 0", "", ""]))
            ws.on_message(receive)

        page.route_web_socket(re.compile(r"^wss://voice\.fixture\.invalid:7443/?$"), sip)
        open_page(page, site, cards="")
        page.evaluate("""() => {
            const card = document.createElement("simson-browser-phone-card");
            card.setConfig({ browser: { realm: "voice.fixture.invalid", websocket: "wss://voice.fixture.invalid:7443",
                extension: "100", outbound_routes: [{name: "Gateway", prefix: "*809"},
                  {name: "WhatsApp", prefix: "*833"}, {name: "Airtel", prefix: "*869250"}] } });
            document.body.append(card);
            card.hass = window.hass;
        }""")
        card = impl_ready(page, "simson-browser-phone-card")
        card.get_by_label("SIP password").fill("fixture-password")
        card.get_by_role("button", name="Connect", exact=True).click()
        card.get_by_text("Ready", exact=True).wait_for(timeout=6000)
        for mode, label, number, route in [
            ("auto", "Extension or dial code", "1202", None),
            ("auto", "Extension or dial code", "*81", None),
            ("outside", "Phone number", "+15551234567", "*833"),
            ("outside", "Phone number", "09123456789", "*869250"),
        ]:
            card.get_by_label("Call through").select_option(mode)
            card.get_by_label(label, exact=True).fill(number)
            if route:
                card.get_by_label("Outbound route").select_option(route)
                assert not card.get_by_role("button", name="Video call").is_visible()
            card.get_by_role("button", name="Audio call").click()
            card.locator("#dial").wait_for(state="visible", timeout=6000)
        assert invites == [f"sip:1202@{realms}", f"sip:*81@{realms}",
                           f"sip:*833+15551234567@{realms}", f"sip:*86925009123456789@{realms}"]
        assert page.evaluate("window.calls") == []
        browser.close()
