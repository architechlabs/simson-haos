import assert from "node:assert/strict";
import test from "node:test";
import { joinSession } from "../src/session.js";

globalThis.location = { origin: "https://home.fixture.invalid" };
const line = { realm: "voice.fixture.invalid", extension: "201", websocket: "wss://voice.fixture.invalid:7443/", relay: "" };

test("split cards share one call, with one controller and one media player", (t) => {
  const dock = new Map();
  const joins = [];
  t.after(() => { for (const join of joins) join.leave(); });
  for (const view of ["dialer", "contacts", "controls", "video"]) {
    const join = joinSession({ ...line, title: view }, view,
      (snapshot, layout) => dock.set(view, { snapshot, ...layout }));
    joins.push(join);
  }
  const group = joins[0].group;
  assert.ok(joins.every((join) => join.group === group));
  assert.ok(dock.get("controls").primary);
  assert.ok(dock.get("video").media);
  assert.equal([...dock.values()].filter((view) => view.primary || view.media).length, 2);
  group.camera(true);
  group.report("Shared call state");
  assert.ok([...dock.values()].every((view) => view.shareCamera && view.snapshot.message === "Shared call state"));
  joins.pop().leave();
  assert.ok(dock.get("controls").media, "call controls take over playback when the video card is removed");
  assert.throws(() => joinSession({ ...line, websocket: "wss://voice.fixture.invalid:7444/" }, "combined", () => {}));
});

test("navigation keeps an opted-in SIP session scoped to its location", async () => {
  const retained = { ...line, extension: "202", keepConnected: true };
  const first = joinSession(retained, "combined", () => {});
  let closed = 0;
  first.group.phone = { close: () => { closed += 1; } };
  first.leave();
  await new Promise((resolve) => setTimeout(resolve, 400));

  const next = joinSession(retained, "combined", () => {});
  const regular = joinSession({ ...retained, keepConnected: false }, "dialer", () => {});
  const other = joinSession({ ...retained, realm: "other.fixture.invalid" }, "combined", () => {});
  assert.equal(next.group, first.group);
  assert.notEqual(next.group, other.group);
  assert.equal(closed, 0);

  next.leave();
  regular.leave();
  other.leave();
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(closed, 1);
});
