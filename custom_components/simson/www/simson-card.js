// Simson: tiny entry point, loaded on every Home Assistant page.
//
// It does three things and nothing else:
//  1. defines every card element immediately, so Home Assistant never renders
//     "Configuration error" while a card downloads;
//  2. installs window.simson, the call API for scripts and custom dashboards;
//  3. starts the call runtime and loads dashboard controls only when needed.
// Everything heavy lives in simson-card-core.js (cards) and simson-runtime.js
// (global call layer). Keep this file small and dependency free.
const VERSION = "0.1.8";

function brandImage(variant = "mark") {
  const image = document.createElement("img");
  const wordmark = variant === "wordmark";
  image.className = wordmark ? "simson-wordmark" : "simson-mark";
  image.src = new URL(wordmark ? "brand/logo.png" : "brand/icon.png", import.meta.url).href;
  image.alt = wordmark ? "Simson by Architech Labs" : "";
  image.width = wordmark ? 132 : 34;
  image.height = wordmark ? 32 : 34;
  return image;
}

const retrying = (name) => {
  let promise;
  let attempt = 0;
  return () => {
    if (promise) return promise;
    const url = new URL(`./${name}?v=${VERSION}`, import.meta.url);
    // Browsers remember failed module imports by URL until the document closes.
    if (attempt++ > 0) url.searchParams.set("retry", `${Date.now()}-${attempt}`);
    promise = import(url.href).catch((error) => { promise = null; throw error; });
    return promise;
  };
};
const loadCore = retrying("simson-card-core.js");
const loadRuntime = retrying("simson-runtime.js");

// ---- window.simson -----------------------------------------------------------
if (!window.simson) {
  let manager = null;
  const ensureRuntime = async () => {
    if (!manager) {
      manager = (await loadRuntime()).manager;
      manager.brandImage = brandImage;
    }
    return manager;
  };
  let warmTimer;
  let warmAttempts = 0;
  const warmRuntime = () => {
    clearTimeout(warmTimer);
    if (manager) return;
    ensureRuntime().catch(() => {
      if (warmAttempts < 3 && navigator.onLine) {
        warmTimer = setTimeout(warmRuntime, [700, 1600, 4000][warmAttempts++]);
      }
    });
  };
  const resumeRuntime = () => {
    if (document.visibilityState === "hidden") return;
    warmAttempts = 0;
    warmRuntime();
  };
  const api = {
    version: VERSION,
    get ready() { return ensureRuntime(); },
    // Subscribe to simson:incoming, simson:answered, simson:ended, simson:missed.
    on(type, handler) {
      const listener = (event) => handler(event.detail);
      window.addEventListener(`simson:${type}`, listener);
      return () => window.removeEventListener(`simson:${type}`, listener);
    },
    get calls() { return manager ? manager.liveCalls : []; },
    get settings() { return manager ? manager.settings : null; },
  };
  for (const name of ["call", "hangup", "answer", "decline", "configure", "mount", "registerTransport", "prepareMedia", "openDialer"]) {
    // Call straight through once loaded so a click keeps its user gesture.
    api[name] = (...args) => (manager ? manager[name](...args) : ensureRuntime().then((m) => m[name](...args)));
  }
  window.simson = api;
  window.addEventListener("online", resumeRuntime);
  document.addEventListener("visibilitychange", resumeRuntime);
  warmRuntime();
}

// ---- cards ---------------------------------------------------------------------
class SimsonCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._impl = null;
    this._retries = 0;
    this._loading = false;
    this._recover = () => {
      if (document.visibilityState === "hidden" || !this.isConnected || this._impl || this.closest("[inert]")) return;
      this._retries = 0;
      void this._mount();
    };
  }

  // Never throws: an empty config is valid because the card discovers its entities.
  setConfig(config) {
    this._config = { view: this.constructor.defaultView, ...(this.constructor.defaultMode && { mode: this.constructor.defaultMode }), ...(config || {}) };
    if (this._config.view === "dial") this._config.view = "dialer";
    if (this._impl) this._impl.setConfig(this._config);
  }

  set hass(value) {
    this._hass = value;
    if (this._impl) this._impl.hass = value;
  }

  connectedCallback() {
    if (this._impl) return;
    if (this.closest("[inert]")) {
      this._preview();
      return;
    }
    if (!this._config.view) this._config = { view: this.constructor.defaultView, ...this._config };
    window.addEventListener("online", this._recover);
    document.addEventListener("visibilitychange", this._recover);
    this._status("Opening Simson…");
    void this._mount();
  }

  disconnectedCallback() {
    clearTimeout(this._timer);
    window.removeEventListener("online", this._recover);
    document.removeEventListener("visibilitychange", this._recover);
  }

  async _mount() {
    if (this._loading || this._impl) return;
    clearTimeout(this._timer);
    this._loading = true;
    try {
      const [{ createCard }] = await Promise.all([loadCore(), window.simson.ready]);
      if (!this.isConnected || this.closest("[inert]")) return;
      const impl = createCard(brandImage);
      impl.setConfig(this._config);
      if (this._hass) impl.hass = this._hass;
      this._impl = impl;
      this.shadowRoot.replaceChildren(impl);
    } catch (error) {
      if (!this.isConnected) return;
      console.warn("[Simson] Dashboard assets could not load", error);
      if (this._retries < 3 && navigator.onLine) {
        this._timer = setTimeout(() => { this._retries += 1; this._mount(); }, [600, 1500, 3500][this._retries]);
      }
      this._status("Simson could not load.", true);
    } finally {
      this._loading = false;
    }
  }

  _status(message, retry = false) {
    const box = document.createElement("div");
    box.setAttribute("role", "status");
    box.style.cssText = "padding:20px;min-height:72px;box-sizing:border-box;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color);font:14px var(--paper-font-body1_-_font-family,system-ui)";
    box.style.display = "flex";
    box.style.alignItems = "center";
    box.style.gap = "10px";
    box.append(brandImage(), message);
    if (retry) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Retry";
      button.style.cssText = "min-height:44px;padding:0 12px;font:inherit";
      button.onclick = this._recover;
      box.append(button);
    }
    this.shadowRoot.replaceChildren(box);
  }

  _preview() {
    const { icon, description } = this.constructor.metadata;
    const box = document.createElement("div");
    box.className = "simson-preview";
    box.style.cssText = "display:grid;gap:10px;padding:14px;justify-items:start;border-radius:var(--ha-card-border-radius,12px);background:var(--card-background-color,#fff);color:var(--secondary-text-color,#576171);font:13px/1.4 system-ui";
    const mark = brandImage("wordmark");
    mark.style.cssText = "box-sizing:content-box;padding:6px 8px;border-radius:7px;background:#f6f5f1;max-width:100%;object-fit:contain";
    const detail = document.createElement("div");
    detail.style.cssText = "display:flex;align-items:center;gap:8px;min-width:0";
    const glyph = document.createElement("ha-icon");
    glyph.setAttribute("icon", icon);
    glyph.setAttribute("aria-hidden", "true");
    glyph.style.cssText = "color:var(--primary-color,#174cc2);flex:none;--mdc-icon-size:18px";
    detail.append(glyph, description);
    box.append(mark, detail);
    this.shadowRoot.replaceChildren(box);
  }

  getCardSize() { return 6; }
  getGridOptions() { return { columns: 12, rows: "auto", min_columns: 6 }; }
  static getStubConfig() { return { type: "custom:simson-card" }; }
}

// One card for everything, plus focused cards that can be placed anywhere.
const CARDS = [
  ["simson-card", "combined", "Simson phone", "mdi:phone-in-talk-outline", "Make and answer calls on this Home Assistant screen."],
  ["simson-relay-card", "combined", "Simson handset relay", "mdi:phone-in-talk-outline", "Connect two physical phones."],
  ["simson-dialer-card", "dialer", "Simson dialer", "mdi:dialpad", "Dial an extension for an audio or video call."],
  ["simson-phones-card", "phones", "Simson phones", "mdi:phone-check-outline", "See phone registration and select a destination."],
  ["simson-live-call-card", "live", "Simson live call", "mdi:phone-outline", "See and control the call in progress."],
  ["simson-add-phone-card", "add", "Simson phone setup", "mdi:phone-outline", "Manage SIP extensions in the Simson portal."],
  ["simson-browser-phone-card", "browser", "Simson browser phone", "mdi:headset", "Talk and answer on this device over WebRTC."],
  ["simson-phone-controls-card", "controls", "Simson phone controls", "mdi:phone-incoming-outline", "Answer, mute and end calls on this Home Assistant screen."],
  ["simson-video-card", "video", "Simson call video", "mdi:video-outline", "Watch the SIP video feed from a door station or another phone."],
  ["simson-history-card", "history", "Simson call history", "mdi:phone-log", "See recent calls and durations."],
  ["simson-dial-card", "dialer", "Simson dial", "mdi:dialpad", "Dial an extension for an audio or video call."],
];
window.customCards = window.customCards || [];
for (const [name, view, title, icon, description] of CARDS) {
  if (!customElements.get(name)) {
    customElements.define(name, class extends SimsonCard {
      static defaultView = view;
      static defaultMode = name === "simson-relay-card" ? "relay" : undefined;
      static metadata = { icon, description };
      static getStubConfig() { return { type: `custom:${name}`, view }; }
    });
  }
  if (!["simson-relay-card", "simson-dial-card", "simson-add-phone-card"].includes(name) && !window.customCards.some((card) => card.type === name)) {
    window.customCards.push({ type: name, name: title, description, preview: true });
  }
}
