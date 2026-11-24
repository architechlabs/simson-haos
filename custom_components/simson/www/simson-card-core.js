// Simson card interface. Loaded lazily by simson-card.js.
//
// The card is a controller: calls, microphone permission and the live-call view
// belong to the global runtime (window.simson), so they keep working on any
// dashboard, panel or custom page. The card only asks for them.

const STYLE = `
:host{display:block}
*{box-sizing:border-box}
.card{display:grid;gap:16px;padding:18px;border-radius:var(--ha-card-border-radius,16px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color);box-shadow:var(--ha-card-box-shadow,none);font-family:var(--paper-font-body1_-_font-family,system-ui)}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.identity{display:flex;align-items:center;gap:8px;min-width:0}
.simson-mark{display:block;flex:none;width:32px;height:32px;border-radius:8px}
.simson-wordmark{display:block;box-sizing:content-box;width:132px;max-width:100%;height:auto;padding:6px 8px;border-radius:8px;background:#f6f5f1}
h2{margin:0;font-size:19px;font-weight:650;letter-spacing:-.01em}
h3{margin:0 0 8px;font-size:12px;font-weight:650;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.06em}
.pill{padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;background:color-mix(in srgb,var(--success-color,#2e7d32) 16%,transparent);color:var(--primary-text-color)}
.row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
.actions{display:flex;gap:10px;flex:1 1 100%}.actions button{flex:1}
label{display:grid;gap:4px;font-size:12px;font-weight:600;color:var(--secondary-text-color)}
.grow{flex:1;min-width:130px}
select,input{width:100%;min-height:46px;padding:0 14px;border:1px solid var(--divider-color);border-radius:14px;background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit;font-size:15px}
input.num{font-size:18px;letter-spacing:.06em;font-variant-numeric:tabular-nums}
button{min-height:46px;padding:0 20px;border:0;border-radius:999px;background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;font-weight:650;cursor:pointer;transition:transform .12s ease,filter .12s ease}
button:hover:not(:disabled){filter:brightness(1.07)}button:active:not(:disabled){transform:scale(.97)}
button.quiet{background:transparent;color:var(--primary-text-color);border:1px solid var(--divider-color)}
button.video{background:color-mix(in srgb,var(--primary-color) 14%,transparent);color:var(--primary-text-color)}
button:disabled{opacity:.45;cursor:not-allowed}
button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid color-mix(in srgb,var(--primary-color) 55%,transparent);outline-offset:2px}
.phones{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.phone{display:flex;align-items:center;gap:12px;min-height:60px;padding:10px 14px;border-radius:16px;text-align:left;background:var(--secondary-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);font-weight:600}
.phone.sel{border-color:var(--primary-color);box-shadow:0 0 0 1px var(--primary-color) inset}
.phone small{display:block;font-weight:400;color:var(--secondary-text-color)}
.dot{flex:none;width:11px;height:11px;border-radius:50%;background:var(--disabled-text-color,#9e9e9e)}
.dot.on{background:var(--success-color,#2e7d32);box-shadow:0 0 0 4px color-mix(in srgb,var(--success-color,#2e7d32) 22%,transparent)}.dot.off{background:var(--error-color,#c0392b)}
.empty{margin:0;padding:18px;border-radius:14px;text-align:center;color:var(--secondary-text-color);background:var(--secondary-background-color)}
.note{margin:0;font-size:13px;color:var(--secondary-text-color)}
.history{margin:0;padding:0;list-style:none}.history li{display:flex;justify-content:space-between;gap:8px;padding:10px 0;border-block-end:1px solid var(--divider-color)}
.error,.ok{padding:10px 14px;border-radius:12px;font-size:13px}
.error{background:color-mix(in srgb,var(--error-color,#c0392b) 14%,transparent)}.ok{background:color-mix(in srgb,var(--success-color,#2e7d32) 16%,transparent)}
`;

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  node.append(...children.flat().filter((child) => child != null && child !== false));
  return node;
};

class SimsonCardImpl extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._view = "combined";
    this._hass = null;
    this._busy = false;
    this._message = null;
    try { this._from = localStorage.getItem("simson.from") || ""; } catch { this._from = ""; }
    this._to = "";
    this._unmount = null;
    this._slot = null;
  }

  setConfig(config) {
    const next = config || {};
    if (next.browser !== this._config.browser || next.view !== this._config.view) {
      this._browserCard = null;
      this._browserFailed = false;
    }
    this._config = next;
    this._view = next.view || "combined";
    this._render();
  }
  set hass(value) {
    const first = !this._hass;
    const previousStates = this._hass?.states;
    this._hass = value;
    if (this._browserCard) {
      this._browserCard.hass = value;
    } else if (first) {
      this._render();
    } else if (value?.states !== previousStates && !this._refreshFrame && this._hasPhoneControls()) {
      this._refreshFrame = requestAnimationFrame(() => {
        this._refreshFrame = 0;
        if (this.isConnected) this._refreshPhoneInventory();
      });
    }
  }

  _hasPhoneControls() { return ["combined", "dialer", "phones"].includes(this._view); }

  _refreshPhoneInventory() {
    const phones = this._phones();
    const changes = JSON.stringify(phones);
    if (changes !== this._phoneInventory) this._render(phones);
  }
  connectedCallback() { this._render(); }
  disconnectedCallback() {
    cancelAnimationFrame(this._refreshFrame);
    this._refreshFrame = 0;
    this._unmount?.();
    this._unmount = null;
    this._slot = null;
  }

  // ---- discovery ----------------------------------------------------------

  _phones() {
    const states = this._hass?.states || {};
    const location = this._config.config_entry_id;
    return Object.values(states)
      .filter((state) => state.attributes?.simson_extension && state.entity_id.startsWith("binary_sensor.") && (!location || state.attributes.config_entry_id === location))
      .map((state) => ({ number: String(state.attributes.simson_extension), name: state.attributes.name || "", gateway: !!state.attributes.gateway, enabled: state.attributes.enabled !== false, online: state.state === "on" ? true : state.state === "off" ? false : null }))
      .sort((a, b) => a.number.localeCompare(b.number, undefined, { numeric: true }));
  }

  // ---- actions ------------------------------------------------------------

  async _run(task) {
    if (this._busy) return;
    this._busy = true;
    this._message = null;
    this._render();
    try { await task(); } catch (error) { this._message = { kind: "error", text: error?.message || "Simson could not do that." }; }
    finally { this._busy = false; this._render(); }
  }

  // Placing a call goes through the global runtime, which asks for the microphone
  // (and camera for video) right now, at the same time as the call starts.
  _placeCall(video) {
    return this._run(async () => {
      await window.simson.call(this._from, this._to, { video, config_entry_id: this._config.config_entry_id });
      this._message = { kind: "ok", text: `Calling ${this._to}. Both phones will ring.` };
    });
  }

  // ---- rendering ----------------------------------------------------------

  _render(knownPhones) {
    if (!this._hass) return;
    if (this._view === "browser" || this._config.browser && ["combined", "dialer"].includes(this._view)) {
      this._renderBrowserPhone();
      return;
    }
    const phones = knownPhones ?? (this._hasPhoneControls() ? this._phones() : []);
    this._phoneInventory = JSON.stringify(phones);
    const callable = phones.filter((phone) => !phone.gateway && phone.enabled);
    if (!this._from || !callable.some((phone) => phone.number === this._from)) this._from = callable.find((phone) => phone.online === true)?.number || callable[0]?.number || "";
    const view = this._view;
    const parts = [];
    const headings = { dialer: "Dialer", phones: "Phones", live: "Live call", add: "Phone setup", history: "Call history" };
    if (headings[view]) parts.push(el("div", { class: "identity" }, this.brandImage?.(), el("h2", {}, this._config.title || headings[view])));
    if (view === "combined") parts.push(this._header(phones), this._dialer(callable), this._phoneGrid(phones), this._live(), this._status());
    else if (view === "dialer") parts.push(this._dialer(callable), this._status());
    else if (view === "phones") parts.push(this._phoneGrid(phones), this._status());
    else if (view === "live") parts.push(this._live());
    else if (view === "history") parts.push(this._history(), this._status());
    else if (view === "add") parts.push(el("p", { class: "note" }, "Manage SIP extensions in the Simson portal."));
    else parts.push(el("p", { class: "empty" }, `Unsupported Simson card view “${view}”.`));
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("div", { class: "card" }, parts.filter(Boolean)));
  }

  _renderBrowserPhone() {
    if (this._browserCard) {
      this._browserCard.hass = this._hass;
      return;
    }
    if (this._browserLoading || this._browserFailed) return;
    if (!this._config.browser) {
      this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("p", { class: "empty" },
        "Configure this card with a Simson browser extension and its secure SIP WebSocket."));
      return;
    }
    void this._loadBrowserPhone();
  }

  async _loadBrowserPhone() {
    const config = this._config.browser;
    const path = new URL("./browser-sip/simson-call-card.js", import.meta.url);
    if (this._browserFailures) path.searchParams.set("retry", Date.now());
    this._browserLoading = true;
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("p", { class: "empty", role: "status" }, "Opening browser phone…"));
    try {
      if (!customElements.get("simson-v2-call-card")) await import(path.href);
      if (config !== this._config.browser) return;
      const card = document.createElement("simson-v2-call-card");
      card.setConfig({ ...config, type: "custom:simson-v2-call-card" });
      card.hass = this._hass;
      this._browserCard = card;
      this.shadowRoot.replaceChildren(card);
    } catch (error) {
      if (config !== this._config.browser) return;
      this._browserFailed = true;
      this._browserFailures = (this._browserFailures || 0) + 1;
      const message = customElements.get("simson-v2-call-card") ? error.message :
        "The browser phone did not load. Retry to download its files.";
      this.shadowRoot.replaceChildren(el("style", {}, STYLE),
        el("div", { class: "card" }, el("p", { role: "alert", class: "note" }, message),
          el("button", { type: "button", class: "quiet", onclick: () => { this._browserFailed = false; this._renderBrowserPhone(); } }, "Retry")));
    } finally {
      this._browserLoading = false;
      if (config !== this._config.browser && this.isConnected) this._render();
    }
  }

  _header(phones) {
    const online = phones.filter((phone) => phone.online).length;
    const identity = this._config.title ? el("div", { class: "identity" }, this.brandImage?.(), el("h2", {}, this._config.title)) : this.brandImage?.("wordmark") ?? el("h2", {}, "Simson");
    return el("div", { class: "top" }, identity, phones.length > 0 && el("span", { class: "pill" }, `${online} online`));
  }

  _status() {
    return this._message && el("div", { class: this._message.kind, role: this._message.kind === "error" ? "alert" : "status" }, this._message.text);
  }

  _history() {
    const refresh = () => this._run(async () => {
      const { config_entry_id } = this._config;
      const { response } = await this._hass.callWS({ type: "call_service", domain: "simson", service: "get_call_history",
        service_data: { limit: 25, ...(config_entry_id ? { config_entry_id } : {}) }, return_response: true });
      if (!Array.isArray(response?.calls)) throw new Error("Call history is temporarily unavailable.");
      this._historyRows = response.calls;
    });
    const rows = this._historyRows;
    return el("div", {}, el("button", { class: "quiet", disabled: this._busy, onclick: refresh },
      this._busy ? "Loading…" : rows ? "Refresh history" : "Load recent calls"),
    rows?.length ? el("ul", { class: "history" }, rows.map((call) => {
      const timestamp = Date.parse(call.started_at);
      const time = Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : "Time unavailable";
      const duration = Math.max(0, Number(call.duration_seconds) || 0);
      const status = call.phase === "ended" ? (call.answered ? "Answered" : "Missed") : call.phase === "active" ? "In call" : "Ringing";
      return el("li", {}, el("span", {}, time), el("span", {}, `${status} · ${duration}s`));
    })) : rows ? el("p", { class: "note" }, "No recent calls.") : null);
  }

  _dialer(callable) {
    if (!callable.length) return el("p", { class: "empty" }, "No enabled phones for phone-to-phone calling. Manage phones in the Simson portal.");
    const disabled = () => this._busy || !this._from || !/^[1-9][0-9]{1,7}$/.test(this._to) || this._from === this._to;
    return el("form", { class: "row", onsubmit: (event) => { event.preventDefault(); if (!disabled()) void this._placeCall(false); } },
      el("label", { class: "grow" }, "Ring this phone first", el("select", { "aria-label": "Call from", onchange: (e) => { this._from = e.target.value; try { localStorage.setItem("simson.from", this._from); } catch {} this._render(); } },
        callable.map((phone) => el("option", { value: phone.number, selected: phone.number === this._from }, `${phone.number} ${phone.name}`.trim())))),
      el("label", { class: "grow" }, "To extension", el("input", { class: "num", value: this._to, inputmode: "numeric", maxlength: 8, placeholder: "1202", "aria-label": "Extension to call", oninput: (e) => { this._to = e.target.value.replace(/\D/g, "");
        e.target.value = this._to;
        for (const button of this.shadowRoot.querySelectorAll(".actions button")) button.disabled = disabled(); } })),
      el("div", { class: "actions" },
        el("button", { type: "submit", disabled: disabled() }, this._busy ? "Calling…" : "Ring phones"),
        this._config.video !== false && el("button", { type: "button", class: "video", disabled: disabled(), onclick: () => this._placeCall(true), "aria-label": "Start a video call" }, "Video")),
      el("p", { class: "note" }, "Pick up the first phone to ring the destination."),
    );
  }

  _phoneGrid(phones) {
    if (!phones.length) return null;
    return el("div", {}, el("h3", {}, "Phones"), el("div", { class: "phones" }, phones.map((phone) => el("button", { class: `phone${phone.number === this._to ? " sel" : ""}`, disabled: phone.gateway || !phone.enabled || this._busy, onclick: () => { this._to = phone.number; this._render(); }, title: phone.online === null ? "Status unknown" : phone.online ? "Online" : "Offline" },
      el("span", { class: `dot ${phone.online === true ? "on" : phone.online === false ? "off" : ""}` }),
      el("span", {}, phone.number, el("small", {}, phone.gateway ? "Carrier gateway" : phone.name || " "))))));
  }

  // One persistent slot, so the live-call view is mounted once and never flickers
  // when Home Assistant pushes a state update.
  _live() {
    if (!window.simson) return null;
    if (!this._slot) {
      const slot = (this._slot = el("div", { class: "live-slot" }));
      Promise.resolve(window.simson.mount(slot, { hideWhenIdle: this._view === "combined" })).then((unmount) => { if (this._slot === slot) this._unmount = unmount; else unmount?.(); });
    }
    return this._slot;
  }


}

if (!customElements.get("simson-card-impl")) customElements.define("simson-card-impl", SimsonCardImpl);
export const createCard = (brandImage) => {
  const card = document.createElement("simson-card-impl");
  card.brandImage = brandImage;
  return card;
};
