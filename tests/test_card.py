"""The cards and the global call layer in a real browser, against a fake Home Assistant."""

import functools
import http.server
import pathlib
import threading
import time

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
      return message.service === "create_extension"
        ? { response: { extension: "1204", username: "1204", server: "sip.example", port: 5061, transport: "tls", password: "one-time-secret" } }
        : { response: { call_id: "new-call", state: "queued" } };
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
      card.setConfig({});
      document.body.append(card);
      card.hass = window.hass;
    }
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
    delay = 0.0
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
        if "simson-card-core.js" in self.path and type(self).delay:
            time.sleep(type(self).delay)
        super().do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    Handler.delay = 0
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


def open_page(page, url, cards="simson-card"):
    page.goto(f"{url}/harness.html?cards={cards}")
    page.wait_for_function("window.ready === true")
    page.wait_for_function("window.__subs && window.__subs.simson_call_event")


def impl_ready(page, tag="simson-card"):
    page.wait_for_function("(tag) => { const host = document.querySelector(tag); return host && host.shadowRoot.querySelector('simson-card-impl'); }", arg=tag)
    return page.locator(f"{tag} >> simson-card-impl")


def shadow_text(locator):
    return locator.evaluate("(node) => node.shadowRoot.textContent")


def overlay(page):
    return page.locator("simson-call-view")


def test_every_card_is_defined_immediately_even_when_the_interface_is_slow(site, page):
    Handler.delay = 1.5
    page.goto(f"{site}/harness.html?cards=simson-card")
    page.wait_for_function("window.ready === true")
    assert page.evaluate("window.definedAtLoad") is True, "the card elements must exist as soon as the entry script runs"
    assert "Opening Simson" in page.locator("simson-card").evaluate("(host) => host.shadowRoot.textContent")
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
    assert len(visible_cards) == 5
    assert page.locator(".simson-preview").count() == 5
    assert page.locator("simson-card-impl").count() == 0
    assert page.get_by_alt_text("Simson by Architech Labs").count() == 5
    assert len(set(page.locator(".simson-preview ha-icon").evaluate_all("icons => icons.map(icon => icon.getAttribute('icon'))"))) == 5
    assert page.evaluate("window.calls.length") == 0
    assert page.evaluate("window.media.requests.length") == 0
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
    inner.get_by_role("button", name="Call", exact=True).click()
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
    assert phones.locator(".phone").count() == 3 and phones.get_by_label("Extension to call").count() == 0


def test_service_errors_are_shown_to_the_user(site, page):
    open_page(page, site)
    inner = impl_ready(page)
    page.evaluate("window.failCalls = true")
    inner.get_by_label("Extension to call").fill("1202")
    inner.get_by_role("button", name="Call", exact=True).click()
    inner.get_by_role("alert").wait_for()
    assert "turned off" in inner.get_by_role("alert").text_content()


def test_adding_a_phone_shows_the_password_once(site, page):
    open_page(page, site)
    inner = impl_ready(page)
    inner.get_by_role("button", name="Add a phone").click()
    inner.get_by_label("Phone name").fill("Garage")
    inner.get_by_label("Extension number").fill("1204")
    inner.get_by_role("button", name="Create").click()
    inner.get_by_text("shown only once").wait_for()
    sent = page.evaluate("window.calls[0][1]")
    assert sent == {"type": "call_service", "domain": "simson", "service": "create_extension", "service_data": {"name": "Garage", "extension": "1204", "notify": False}, "return_response": True}
    assert "one-time-secret" in shadow_text(inner)
    inner.get_by_role("button", name="I have saved it").click()
    assert "one-time-secret" not in shadow_text(inner)
    assert not page.errors, page.errors


def test_a_failed_download_shows_a_retry_message_not_a_configuration_error(site, page):
    page.route("**/simson-card-core.js*", lambda route: route.fulfill(status=500, body="nope"))
    page.goto(f"{site}/harness.html?cards=simson-card")
    page.wait_for_function("window.ready === true")
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.textContent.includes('Reconnecting')", timeout=6000)
    assert "Configuration error" not in page.locator("simson-card").evaluate("(host) => host.shadowRoot.textContent")
