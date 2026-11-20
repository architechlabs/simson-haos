"""The dashboard card in a real browser, against a fake Home Assistant object."""

import functools
import http.server
import json
import pathlib
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")

WWW = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "simson" / "www"

HARNESS = """<!doctype html><meta charset=utf-8><body>
<script type="module">
  import "/simson-card.js";
  window.definedAtLoad = { card: !!customElements.get("simson-card"), relay: !!customElements.get("simson-relay-card") };
  window.calls = [];
  const state = (entity_id, state, attributes) => ({ entity_id, state, attributes });
  window.hass = {
    states: {
      "binary_sensor.kitchen": state("binary_sensor.kitchen", "on", { simson_extension: "1201", name: "Kitchen", enabled: true, gateway: false }),
      "binary_sensor.hall": state("binary_sensor.hall", "off", { simson_extension: "1202", name: "Hall", enabled: true, gateway: false }),
      "binary_sensor.sim": state("binary_sensor.sim", "unknown", { simson_extension: "1701", name: "SIM", enabled: true, gateway: true }),
      "sensor.active": state("sensor.active", "1", { simson_calls: true, calls: [{ id: "call-1", phase: "active", started_at: "2026-11-20T12:00:00Z" }] }),
    },
    callService: async (domain, service, data) => { window.calls.push([domain, service, data]); if (window.failCalls) throw new Error("Extension 1202 is turned off."); },
    callWS: async (message) => { window.calls.push(["ws", message]); return { response: { extension: "1204", username: "1204", server: "sip.example", port: 5061, transport: "tls", password: "one-time-secret" } }; },
  };
  const card = document.createElement("simson-card");
  card.setConfig({});
  document.body.append(card);
  card.hass = window.hass;
  window.card = card;
</script>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    delay = 0.0
    harness = HARNESS
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript"}

    def do_GET(self):
        if self.path.startswith("/harness.html"):
            body = self.harness.encode()
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
    handler = functools.partial(Handler, directory=str(WWW))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", Handler
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
        yield page
        browser.close()


def shadow_text(page):
    return page.evaluate("""() => { const host = document.querySelector('simson-card'); const inner = host.shadowRoot.querySelector('simson-card-impl'); return (inner ? inner.shadowRoot : host.shadowRoot).textContent; }""")


def test_elements_exist_immediately_even_when_the_interface_is_slow(site, page):
    url, handler = site
    handler.delay = 1.5
    page.goto(url + "/harness.html")
    defined = page.evaluate("window.definedAtLoad")
    assert defined == {"card": True, "relay": True}, "the card elements must be defined as soon as the entry script runs"
    assert "Opening Simson" in shadow_text(page)
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.querySelector('simson-card-impl')", timeout=8000)
    assert "Kitchen" in shadow_text(page)
    assert not page.errors, page.errors


def test_lists_phones_with_status_and_disables_gateways(site, page):
    url, handler = site
    handler.delay = 0
    page.goto(url + "/harness.html")
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.querySelector('simson-card-impl')")
    inner = page.locator("simson-card-impl")
    assert inner.locator(".phone").count() == 3
    assert inner.locator(".phone .dot.on").count() == 1 and inner.locator(".phone .dot.off").count() == 1
    assert inner.locator(".phone[disabled]").count() == 1, "the carrier gateway cannot be called from the card"
    assert "Live calls" in shadow_text(page) and "In call" in shadow_text(page)
    assert not page.errors, page.errors


def test_call_and_hangup_go_through_simson_services(site, page):
    url, handler = site
    handler.delay = 0
    page.goto(url + "/harness.html")
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.querySelector('simson-card-impl')")
    inner = page.locator("simson-card-impl")
    assert inner.get_by_role("button", name="Call", exact=True).is_disabled()
    inner.get_by_label("Extension to call").fill("1202")
    inner.get_by_role("button", name="Call", exact=True).click()
    page.wait_for_function("() => window.calls.length === 1")
    assert page.evaluate("window.calls[0]") == ["simson", "call", {"from_extension": "1201", "to_extension": "1202"}]
    assert "Calling 1202" in shadow_text(page)
    inner.get_by_role("button", name="Hang up").click()
    page.wait_for_function("() => window.calls.length === 2")
    assert page.evaluate("window.calls[1]") == ["simson", "hangup", {"call_id": "call-1"}]
    assert not page.errors, page.errors


def test_service_errors_are_shown_to_the_user(site, page):
    url, handler = site
    handler.delay = 0
    page.goto(url + "/harness.html")
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.querySelector('simson-card-impl')")
    page.evaluate("window.failCalls = true")
    inner = page.locator("simson-card-impl")
    inner.get_by_label("Extension to call").fill("1202")
    inner.get_by_role("button", name="Call", exact=True).click()
    inner.get_by_role("alert").wait_for()
    assert "turned off" in inner.get_by_role("alert").text_content()


def test_adding_a_phone_shows_the_password_once(site, page):
    url, handler = site
    handler.delay = 0
    page.goto(url + "/harness.html")
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.querySelector('simson-card-impl')")
    inner = page.locator("simson-card-impl")
    inner.get_by_role("button", name="Add a phone").click()
    inner.get_by_label("Phone name").fill("Garage")
    inner.get_by_label("Extension number").fill("1204")
    inner.get_by_role("button", name="Create").click()
    inner.get_by_text("shown only once").wait_for()
    message = page.evaluate("window.calls[0][1]")
    assert message == {"type": "call_service", "domain": "simson", "service": "create_extension", "service_data": {"name": "Garage", "extension": "1204", "notify": False}, "return_response": True}
    assert "one-time-secret" in shadow_text(page)
    inner.get_by_role("button", name="I have saved it").click()
    assert "one-time-secret" not in shadow_text(page), "the password must disappear once acknowledged"
    assert not page.errors, page.errors


def test_a_failed_download_shows_a_retry_message_not_a_configuration_error(site, page):
    url, handler = site
    handler.delay = 0
    page.route("**/simson-card-core.js*", lambda route: route.fulfill(status=500, body="nope"))
    page.goto(url + "/harness.html")
    page.wait_for_function("() => document.querySelector('simson-card').shadowRoot.textContent.includes('Reconnecting')", timeout=6000)
    text = shadow_text(page)
    assert "Configuration error" not in text
