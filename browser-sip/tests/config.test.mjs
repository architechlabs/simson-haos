import assert from "node:assert/strict";
import test from "node:test";
import { extension, readConfig } from "../src/config.js";
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
