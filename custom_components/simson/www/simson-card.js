// Simson: tiny entry point, loaded on every Home Assistant page.
//
// It does three things and nothing else:
//  1. defines every card element immediately, so Home Assistant never renders
//     "Configuration error" while a card downloads;
//  2. installs window.simson, the call API for scripts and custom dashboards;
//  3. starts downloading the card interface and the call runtime in parallel.
// Everything heavy lives in simson-card-core.js (cards) and simson-runtime.js
// (global call layer). Keep this file small and dependency free.
const VERSION = "0.1.0";
const base = (name) => new URL(`./${name}?v=${VERSION}`, import.meta.url).href;
const retrying = (name) => {
  let promise;
  return () => (promise ||= import(base(name)).catch((error) => { promise = null; throw error; }));
};
const loadCore = retrying("simson-card-core.js");
const loadRuntime = retrying("simson-runtime.js");

// ---- window.simson -----------------------------------------------------------
if (!window.simson) {
  let manager = null;
  const ready = loadRuntime().then((runtime) => (manager = runtime.manager));
  const api = {
    version: VERSION,
    ready,
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
    api[name] = (...args) => (manager ? manager[name](...args) : ready.then((m) => m[name](...args)));
  }
  window.simson = api;
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
  }

  // Never throws: an empty config is valid because the card discovers its entities.
  setConfig(config) {
    this._config = { view: this.constructor.defaultView, ...(config || {}) };
    if (this._impl) this._impl.setConfig(this._config);
  }

  set hass(value) {
    this._hass = value;
    if (this._impl) this._impl.hass = value;
  }

  connectedCallback() {
    if (this._impl) return;
    if (!this._config.view) this._config = { view: this.constructor.defaultView, ...this._config };
    this._status("Opening Simson…");
    this._mount();
  }

  disconnectedCallback() { clearTimeout(this._timer); }

  async _mount() {
    try {
      const { createCard } = await loadCore();
      if (!this.isConnected || this._impl) return;
      const impl = createCard();
      impl.setConfig(this._config);
      if (this._hass) impl.hass = this._hass;
      this._impl = impl;
      this.shadowRoot.replaceChildren(impl);
    } catch (error) {
      console.error("[Simson] the card could not load", error);
      if (this._retries < 3 && this.isConnected) {
        this._timer = setTimeout(() => { this._retries += 1; this._mount(); }, [600, 1500, 3500][this._retries]);
        this._status("Reconnecting to Simson…");
      } else {
        this._status("Simson could not load. Reload this page.");
      }
    }
  }

  _status(message) {
    const box = document.createElement("div");
    box.setAttribute("role", "status");
    box.style.cssText = "padding:20px;min-height:72px;box-sizing:border-box;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color);font:14px var(--paper-font-body1_-_font-family,system-ui)";
    box.textContent = message;
    this.shadowRoot.replaceChildren(box);
  }

  getCardSize() { return 6; }
  getGridOptions() { return { columns: 12, rows: "auto", min_columns: 6 }; }
  static getStubConfig() { return { type: "custom:simson-card" }; }
}

// One card for everything, plus focused cards that can be placed anywhere.
const CARDS = [
  ["simson-card", "combined", "Simson", "Dial, see who is online, hang up and add phones."],
  ["simson-relay-card", "combined", "Simson (compatibility)", "Same as the Simson card."],
  ["simson-dialer-card", "dialer", "Simson dialer", "Just the dialer."],
  ["simson-phones-card", "phones", "Simson phones", "Who is online; tap a phone to call it."],
  ["simson-live-call-card", "live", "Simson live call", "The call in progress, with its controls, wherever you want it."],
  ["simson-add-phone-card", "add", "Simson add phone", "Create a phone and see its settings once."],
];
window.customCards = window.customCards || [];
for (const [name, view, title, description] of CARDS) {
  if (!customElements.get(name)) {
    customElements.define(name, class extends SimsonCard {
      static defaultView = view;
      static getStubConfig() { return { type: `custom:${name}`, view }; }
    });
  }
  if (name !== "simson-relay-card" && !window.customCards.some((card) => card.type === name)) {
    window.customCards.push({ type: name, name: title, description, preview: false });
  }
}

// Start loading the interface and the call runtime now; nothing waits for a dashboard.
loadCore().catch(() => {});
