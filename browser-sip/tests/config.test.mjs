import assert from "node:assert/strict";
import test from "node:test";
import { dialDestination, extension, readConfig, sipDestination } from "../src/config.js";
import { supportsVideo } from "../src/browser-phone.js";

const config = {
  realm: "office.sip.example.net",
  websocket: "wss://office.sip.example.net:7443",
  extension: 203,
  contacts: [
    { name: "Reception", extension: 201 },
    { name: "Door", extension: "202", video: true },
  ],
};

test("reads non-secret SIP settings and keeps contact destinations scoped to the realm", () => {
  const settings = readConfig(config);
  assert.equal(settings.websocket, "wss://office.sip.example.net:7443/");
  assert.equal(settings.extension, "203");
  assert.deepEqual(settings.contacts, [
    { name: "Reception", extension: "201", video: false },
    { name: "Door", extension: "202", video: true },
  ]);
});

test("rejects plaintext signaling, mismatched realms, injected SIP URIs and saved secrets", () => {
  for (const websocket of [
    "ws://office.sip.example.net:7443",
    "wss://another.example.net:7443",
    "wss://user:secret@office.sip.example.net",
    "wss://office.sip.example.net?credential=x",
    "wss://office.sip.example.net/#session",
  ]) assert.throws(() => readConfig({ ...config, websocket }));

  for (const number of ["sip:201@elsewhere.example.net", "+15551234567", "201;transport=tcp", 1.5, "0201"]) {
    assert.throws(() => extension(number));
  }
  for (const field of ["password", "sip_password", "ice_servers"]) {
    assert.throws(() => readConfig({ ...config, [field]: "fixture" }));
  }
  assert.throws(() => readConfig({ ...config, contacts: [{ extension: 203 }] }));
});

test("only a negotiated nonzero video m-line enables the incoming video controls", () => {
  assert.ok(supportsVideo("v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"));
  assert.equal(supportsVideo("v=0\r\nm=video 0 UDP/TLS/RTP/SAVPF 96\r\n"), false);
  assert.equal(supportsVideo(undefined), false);
});

test("routes local dial codes and prefixed outside calls without accepting injected SIP addresses", () => {
  assert.equal(dialDestination("201", "extension"), "201");
  assert.equal(dialDestination("*81", "route"), "*81");
  assert.equal(sipDestination(dialDestination("+15551234567", "outside", "*9")), "*9+15551234567");
  assert.equal(sipDestination(dialDestination("+919123456789", "outside", "*869250")), "*869250+919123456789");
  assert.equal(readConfig({ ...config, registration_realm: "s-pin.vipsy.in" }).registrationRealm, "s-pin.vipsy.in");
  assert.throws(() => readConfig({ ...config, registration_realm: "different.example.test" }));
  assert.deepEqual(readConfig({ ...config, outbound_routes: [
    { prefix: "*833", name: "WhatsApp" }, { prefix: "*859", name: "Airtel" },
  ] }).routes.map(({prefix}) => prefix), ["*833", "*859"]);
  assert.equal(sipDestination(dialDestination("00915551234567", "outside", "9")), "900915551234567");
  for (const text of ["+15551234567", "201@example.test", "201;user=phone", "201?x=y", "201\r\n", "#100"]) {
    assert.throws(() => sipDestination(text));
  }
  assert.throws(() => dialDestination("+15551234567", "outside"));
  assert.throws(() => dialDestination("*81", "extension"));
  assert.throws(() => dialDestination("+15551234567", "auto"));
  const contacts = [{ name: "Delivery", extension: "+15551234567", mode: "outside" }];
  assert.equal(readConfig({ ...config, gateway_prefix: "*9", contacts }).contacts[0].extension, "*9+15551234567");
  assert.throws(() => readConfig({ ...config, gateway_prefix: "*9", contacts: [{ ...contacts[0], video: true }] }));
});
