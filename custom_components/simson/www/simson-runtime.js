// Simson runtime: the global call layer.
//
// Loaded on every Home Assistant page by simson-card.js. It owns call state and
// the call user interface, independent of any card, so calls ring and can be
// answered or ended from whatever dashboard, panel or custom page you are on.
// Cards, scripts and custom dashboards only trigger it:
//
//   window.simson.call("1201", "1202")        place a call
//   window.simson.on("incoming", (call) => …)  react to calls (also DOM events)
//   window.simson.configure({ overlay: false }) hide the built-in overlay
//   window.simson.mount(element)               render the live-call view anywhere
//   window.simson.registerTransport(t)         plug in a media transport
//
// DOM events on window: simson:incoming, simson:answered, simson:ended,
// simson:missed. Each carries the call in event.detail.

const SETTINGS_KEY = "simson.settings";
const LIVE = ["requesting", "ringing", "active"];
const defaultSettings = { overlay: true, position: "bottom-right", sound: false };

const STYLE = `
:host{all:initial}
*{box-sizing:border-box}
.panel{position:fixed;z-index:2147483000;width:min(380px,calc(100vw - 24px));padding:18px;border-radius:22px;background:color-mix(in srgb,var(--card-background-color,#fff) 94%,transparent);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);color:var(--primary-text-color,#111);border:1px solid color-mix(in srgb,var(--divider-color,#ccc) 70%,transparent);box-shadow:0 18px 60px rgba(0,0,0,.38);font:14px/1.45 var(--paper-font-body1_-_font-family,system-ui);display:grid;gap:14px;animation:rise .28s cubic-bezier(.2,.8,.2,1)}
.panel.bottom-right{right:14px;bottom:14px}.panel.bottom-left{left:14px;bottom:14px}.panel.top-right{right:14px;top:14px}.panel.top-left{left:14px;top:14px}
.panel.inline{position:static;width:auto;box-shadow:none;animation:none;background:var(--card-background-color,#fff)}
@keyframes rise{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
.head{display:flex;align-items:center;gap:14px}
.head .simson-mark{flex:none;margin-inline-start:auto;width:28px;height:28px;border-radius:7px}
.avatar{position:relative;flex:none;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,var(--primary-color,#03a9f4),color-mix(in srgb,var(--primary-color,#03a9f4) 55%,#6a1b9a))}
.avatar svg{width:24px;height:24px;fill:currentColor}
.avatar.ringing::after,.avatar.active::after{content:"";position:absolute;inset:-5px;border-radius:50%;border:2px solid var(--success-color,#2e7d32);opacity:0;animation:ring 1.6s infinite}
.avatar.ringing::after{border-color:var(--warning-color,#e08a00)}
@keyframes ring{0%{transform:scale(.9);opacity:.8}100%{transform:scale(1.35);opacity:0}}
@media (prefers-reduced-motion:reduce){.panel{animation:none}.avatar::after{animation:none!important}}
.who{min-width:0}.title{font-size:17px;font-weight:650;letter-spacing:-.01em}.meta{color:var(--secondary-text-color,#666);font-size:13px}
.timer{font-variant-numeric:tabular-nums}
.media{display:none;border-radius:16px;overflow:hidden;background:#0b0b0f;aspect-ratio:16/9}.media.on{display:block}.media video{width:100%;height:100%;object-fit:cover;display:block}
.row{display:flex;gap:8px;flex-wrap:wrap}
button{flex:1;min-height:46px;padding:0 16px;border:0;border-radius:999px;background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);font:inherit;font-weight:650;cursor:pointer;transition:transform .12s ease,filter .12s ease}
button:hover{filter:brightness(1.06)}button:active{transform:scale(.97)}
button.quiet{background:transparent;color:inherit;border:1px solid var(--divider-color,#ccc)}button.danger{background:var(--error-color,#d32f2f)}button.good{background:var(--success-color,#2e7d32)}
button[aria-pressed=true]{background:var(--secondary-text-color,#666);color:#fff}
button:focus-visible{outline:3px solid color-mix(in srgb,var(--primary-color,#03a9f4) 60%,transparent);outline-offset:2px}
.note{font-size:12.5px;color:var(--secondary-text-color,#666);margin:0}
.notice{padding:10px 12px;border-radius:12px;background:color-mix(in srgb,var(--warning-color,#e08a00) 14%,transparent);font-size:13px}
`;

function loadSettings() {
  try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") }; } catch { return { ...defaultSettings }; }
}

const emit = (type, detail) => window.dispatchEvent(new CustomEvent(`simson:${type}`, { detail }));

// The default transport: Simson rings both phones and connects them, so audio is
// phone to phone. A transport with `media: true` (for example SIP over
// WebSocket) can answer in the browser and attach audio and video elements.
const phoneTransport = {
  name: "phone",
  media: false,
  async call(hass, from, to, options) {
    return hass.callWS({ type: "call_service", domain: "simson", service: "call", service_data: { from_extension: from, to_extension: to, ...(options?.video ? { video: true } : {}) }, return_response: true });
  },
  async hangup(hass, callId) { return hass.callService("simson", "hangup", { call_id: callId }); },
};

class Manager {
  constructor() {
    this.settings = loadSettings();
    this.calls = new Map();
    this.transports = [phoneTransport];
    this.transport = phoneTransport;
    this._connection = null;
    this.localStream = null;
    this.mediaError = "";
    this._dismissed = new Set();
    this._overlay = null;
    this._timer = null;
    this._unsubs = [];
    this._views = new Set();
    const resume = () => { if (document.visibilityState !== "hidden") this._start(); };
    window.addEventListener("online", resume);
    document.addEventListener("visibilitychange", resume);
    this._start();
  }

  // ---- connection to Home Assistant --------------------------------------

  _hass() { return document.querySelector("home-assistant")?.hass || null; }

  _start() {
    clearTimeout(this._attachTimer);
    const hass = this._hass();
    if (!hass?.connection) {
      this._attachTimer = setTimeout(() => this._start(), document.visibilityState === "hidden" ? 2000 : 400);
      return;
    }
    if (this._connection === hass.connection) return;
    for (const unsubscribe of this._unsubs.splice(0)) void Promise.resolve(unsubscribe()).catch(() => {});
    this._connection = hass.connection;
    void this._subscribe(hass.connection);
  }

  async _subscribe(connection) {
    const subscriptions = [];
    try {
      subscriptions.push(await connection.subscribeEvents((event) => this._onBus(event.data || {}), "simson_call_event"));
      subscriptions.push(await connection.subscribeEvents((event) => { if (this._isOurs(event.data?.entity_id)) this._refresh(); }, "state_changed"));
      if (this._connection !== connection) return;
      this._unsubs = subscriptions.splice(0);
      this._refresh();
    } catch (error) {
      console.warn("[Simson] live updates are unavailable", error);
      if (this._connection === connection) {
        this._connection = null;
        this._attachTimer = setTimeout(() => this._start(), 2500);
      }
    } finally {
      for (const unsubscribe of subscriptions) void Promise.resolve(unsubscribe()).catch(() => {});
    }
  }

  _isOurs(entityId) {
    const state = entityId ? this._hass()?.states?.[entityId] : null;
    return !!state && (state.attributes?.simson_calls || state.attributes?.simson_extension);
  }

  _refresh() {
    const hass = this._hass();
    if (!hass) return;
    const sensor = Object.values(hass.states || {}).find((state) => state.attributes?.simson_calls);
    const live = (sensor?.attributes?.calls || []).filter((call) => LIVE.includes(call.phase));
    const seen = new Set();
    for (const call of live) {
      seen.add(call.id);
      const before = this.calls.get(call.id);
      this.calls.set(call.id, { ...before, ...call });
      if (!before) emit("incoming", this.calls.get(call.id));
      else if (before.phase !== "active" && call.phase === "active") emit("answered", this.calls.get(call.id));
    }
    for (const id of [...this.calls.keys()]) if (!seen.has(id)) this.calls.delete(id);
    if (!this.calls.size && !this.transport.media) this._releaseMedia();
    this._render();
  }

  _onBus(data) {
    if (data.event === "ended" || data.event === "missed") {
      const call = this.calls.get(data.call_id) || { id: data.call_id, phase: "ended" };
      this.calls.delete(data.call_id);
      emit(data.event, { ...call, ...data });
      this._dismissed.delete(data.call_id);
      if (!this.calls.size) this._releaseMedia();
      this._render();
    }
    this._refresh();
  }

  // ---- public API ----------------------------------------------------------

  get liveCalls() { return [...this.calls.values()]; }

  // The moment someone hits Call we ask for the microphone (and the camera for
  // a video call) at the same time as the call is set up, never after the
  // connection. getUserMedia has to start before the first await to count as
  // part of the click, so keep this method's opening synchronous.
  call(from, to, options = {}) {
    const hass = this._hass();
    if (!hass) return Promise.reject(new Error("Home Assistant is not ready yet."));
    const wantsMedia = options.requestMedia ?? this.transport.media;
    const media = wantsMedia ? this.prepareMedia({ video: !!options.video }) : Promise.resolve(null);
    return this._place(hass, String(from), String(to), options, media);
  }

  async _place(hass, from, to, options, media) {
    const [result] = await Promise.all([this.transport.call(hass, from, to, { ...options, media }), media.catch(() => null)]);
    this._refresh();
    return result?.response ?? result;
  }

  // Ask for permission now so the browser prompt is answered while the call is
  // still being set up. Resolves to the stream, or null with mediaError set.
  async prepareMedia({ video = false } = {}) {
    if (this.localStream && (!video || this.localStream.getVideoTracks().length)) return this.localStream;
    if (!navigator.mediaDevices?.getUserMedia) { this.mediaError = "This browser cannot use a microphone here. Open Home Assistant over HTTPS."; this._render(); return null; }
    this._releaseMedia();
    try {
      this.localStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: video ? { facingMode: "user" } : false });
      this.mediaError = "";
      emit("media", { ready: true, video: this.localStream.getVideoTracks().length > 0 });
    } catch (error) {
      this.localStream = null;
      this.mediaError = error?.name === "NotAllowedError" ? "Microphone access is blocked. Allow it in your browser site settings, then try again."
        : error?.name === "NotFoundError" ? (video ? "No camera or microphone was found." : "No microphone was found.")
        : "The microphone could not be started.";
      emit("media", { ready: false, error: this.mediaError });
    }
    this._render();
    return this.localStream;
  }

  _releaseMedia() {
    this.localStream?.getTracks().forEach((track) => track.stop());
    this.localStream = null;
  }

  async hangup(callId) {
    const hass = this._hass();
    if (!hass) throw new Error("Home Assistant is not ready yet.");
    await this.transport.hangup(hass, callId);
    this._refresh();
  }

  // Answering in the browser needs a transport with media. With the phone
  // transport the call is answered on the phone itself.
  async answer(callId) {
    if (!this.transport.answer) throw new Error("This call is answered on the phone. Pick up the handset.");
    return this.transport.answer(this._hass(), callId, this._mediaHost());
  }

  async decline(callId) {
    return this.transport.decline ? this.transport.decline(this._hass(), callId) : this.hangup(callId);
  }

  configure(options = {}) {
    this.settings = { ...this.settings, ...options };
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings)); } catch { /* storage may be blocked */ }
    this._render();
    return this.settings;
  }

  registerTransport(transport) {
    if (!transport?.name || typeof transport.call !== "function" || typeof transport.hangup !== "function") throw new Error("A transport needs a name, call() and hangup().");
    this.transports = [...this.transports.filter((item) => item.name !== transport.name), transport];
    this.transport = transport;
    return () => { this.transports = this.transports.filter((item) => item !== transport); if (this.transport === transport) this.transport = phoneTransport; };
  }

  openDialer() { emit("dialer", {}); }

  // Render the live-call view into any element: a custom dashboard, a dialog, a
  // wall-panel layout. The overlay uses the same view.
  mount(container, options = {}) {
    const view = new CallView(this, { inline: true, ...options });
    container.append(view);
    this._views.add(view);
    return () => { view.remove(); this._views.delete(view); };
  }

  _mediaHost() { return this._overlay?.shadowRoot?.querySelector(".media") || null; }

  // ---- overlay -----------------------------------------------------------

  _render() {
    for (const view of this._views) view.update();
    const wanted = this.settings.overlay !== false && this.liveCalls.some((call) => !this._dismissed.has(call.id));
    if (wanted && !this._overlay) {
      this._overlay = new CallView(this, { inline: false });
      document.body.append(this._overlay);
      this._tick();
    } else if (!wanted && this._overlay) {
      this._overlay.remove();
      this._overlay = null;
      clearInterval(this._timer);
    }
    this._overlay?.update();
  }

  _tick() {
    clearInterval(this._timer);
    this._timer = setInterval(() => { this._overlay?.update(); for (const view of this._views) view.update(); }, 1000);
  }

  dismiss(callId) { this._dismissed.add(callId); this._render(); }
}

function elapsed(call) {
  const start = Date.parse(call.connected_at || call.started_at || "");
  if (!start) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

class CallView extends HTMLElement {
  constructor(manager, options) {
    super();
    this._manager = manager;
    this._options = options;
    this.attachShadow({ mode: "open" });
    this._error = "";
    this.update();
  }

  update() {
    const m = this._manager;
    const calls = this._options.callId ? m.liveCalls.filter((call) => call.id === this._options.callId) : m.liveCalls.filter((call) => this._options.inline || !m._dismissed.has(call.id));
    const style = document.createElement("style");
    style.textContent = STYLE;
    const panels = calls.map((call) => this._panel(call));
    if (!calls.length && this._options.inline && !this._options.hideWhenIdle) {
      const empty = document.createElement("div");
      empty.className = "panel inline";
      empty.innerHTML = '<div class="meta">No call in progress.</div>';
      panels.push(empty);
    }
    this.shadowRoot.replaceChildren(style, ...panels);
  }

  _panel(call) {
    const m = this._manager;
    const active = call.phase === "active";
    const panel = document.createElement("div");
    panel.className = `panel ${this._options.inline ? "inline" : m.settings.position}`;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", active ? "Call in progress" : "Incoming call");
    panel.setAttribute("aria-live", "polite");
    const head = document.createElement("div");
    head.className = "head";
    const avatar = document.createElement("div");
    avatar.className = `avatar ${active ? "active" : "ringing"}`;
    avatar.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.6a1 1 0 0 1-.25 1z"/></svg>';
    const who = document.createElement("div");
    who.className = "who";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = active ? "In call" : "Incoming call";
    const meta = document.createElement("div");
    meta.className = "meta";
    if (active) { const time = document.createElement("span"); time.className = "timer"; time.textContent = elapsed(call); meta.append("Connected \u00b7 ", time); }
    else meta.textContent = `Ringing since ${new Date(call.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    who.append(title, meta);
    head.append(avatar, who);
    if (m.brandImage) head.append(m.brandImage());
    const media = document.createElement("div");
    media.className = `media${m.transport.media ? " on" : ""}`;
    const row = document.createElement("div");
    row.className = "row";
    const button = (label, className, handler, pressed) => {
      const node = document.createElement("button");
      node.type = "button";
      node.textContent = label;
      if (className) node.className = className;
      if (pressed !== undefined) node.setAttribute("aria-pressed", String(pressed));
      node.addEventListener("click", async () => {
        try { this._error = ""; await handler(); } catch (error) { this._error = error?.message || "That did not work."; this.update(); }
      });
      return node;
    };
    if (!active && m.transport.answer) row.append(button("Answer", "good", () => m.answer(call.id)));
    row.append(button(active ? "Hang up" : m.transport.answer ? "Decline" : "Hang up", "danger", () => (active ? m.hangup(call.id) : m.decline(call.id))));
    const stream = m.localStream;
    if (stream) {
      const audio = stream.getAudioTracks()[0];
      if (audio) row.append(button(audio.enabled ? "Mute" : "Unmute", "quiet", () => { audio.enabled = !audio.enabled; this.update(); }, !audio.enabled));
      const video = stream.getVideoTracks()[0];
      if (video) row.append(button(video.enabled ? "Camera off" : "Camera on", "quiet", () => { video.enabled = !video.enabled; this.update(); }, !video.enabled));
    }
    if (!this._options.inline) row.append(button("Dismiss", "quiet", () => m.dismiss(call.id)));
    panel.append(head, media, row);
    if (!active && !m.transport.answer) {
      const note = document.createElement("p");
      note.className = "note";
      note.textContent = "Answer on your phone. Audio goes phone to phone, so there is nothing to wait for.";
      panel.append(note);
    }
    const problem = this._error || m.mediaError;
    if (problem) {
      const notice = document.createElement("div");
      notice.className = "notice";
      notice.setAttribute("role", "alert");
      notice.textContent = problem;
      panel.append(notice);
    }
    return panel;
  }
}

if (!customElements.get("simson-call-view")) customElements.define("simson-call-view", CallView);

export const manager = new Manager();
