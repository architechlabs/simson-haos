// Simson card: tiny entry point.
//
// This file defines the custom elements the moment it runs, so Home Assistant
// never renders "Configuration error" while the card downloads. Everything heavy
// lives in simson-card-core.js, which starts downloading in parallel right away
// and is swapped in as soon as it is ready. Keep this file small and dependency
// free.
const VERSION = "0.1.0";
const CORE = new URL(`./simson-card-core.js?v=${VERSION}`, import.meta.url).href;

let corePromise;
const loadCore = () => (corePromise ||= import(CORE).catch((error) => { corePromise = null; throw error; }));

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
    this._config = { ...(config || {}) };
    if (this._impl) this._impl.setConfig(this._config);
  }

  set hass(value) {
    this._hass = value;
    if (this._impl) this._impl.hass = value;
  }

  connectedCallback() {
    if (this._impl) return;
    this._status("Opening Simson…");
    this._mount();
  }

  disconnectedCallback() {
    clearTimeout(this._timer);
  }

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

for (const name of ["simson-card", "simson-relay-card"]) {
  if (!customElements.get(name)) customElements.define(name, class extends SimsonCard {});
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "simson-card")) {
  window.customCards.push({ type: "simson-card", name: "Simson", description: "Call between phones, see who is online, add phones.", preview: false });
}

// Begin loading the real card now; do not wait for a dashboard to ask for it.
loadCore().catch(() => {});
