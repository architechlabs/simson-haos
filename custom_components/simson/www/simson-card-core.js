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
dl{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;margin:10px 0}dt{color:var(--secondary-text-color)}dd{margin:0;font-family:var(--code-font-family,monospace);user-select:all;overflow-wrap:anywhere}
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
    this._created = null;
    this._form = false;
    try { this._from = localStorage.getItem("simson.from") || ""; } catch { this._from = ""; }
    this._to = "";
    this._unmount = null;
    this._slot = null;
  }

  setConfig(config) { this._config = config || {}; this._view = this._config.view || "combined"; this._render(); }
  set hass(value) { this._hass = value; this._render(); }
  connectedCallback() { this._render(); }
  disconnectedCallback() { this._unmount?.(); this._unmount = null; this._slot = null; }

  // ---- discovery ----------------------------------------------------------

  _phones() {
    const states = this._hass?.states || {};
    return Object.values(states)
      .filter((state) => state.attributes?.simson_extension && state.entity_id.startsWith("binary_sensor."))
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
      if (window.simson) await window.simson.call(this._from, this._to, { video });
      else await this._hass.callService("simson", "call", { from_extension: this._from, to_extension: this._to, ...(video ? { video: true } : {}) });
      this._message = { kind: "ok", text: `Calling ${this._to}. Both phones will ring.` };
    });
  }

  _create(form) {
    const name = form.querySelector("[name=name]").value.trim();
    const extension = form.querySelector("[name=extension]").value.trim();
    return this._run(async () => {
      const result = await this._hass.callWS({ type: "call_service", domain: "simson", service: "create_extension", service_data: { name, extension, notify: false }, return_response: true });
      this._created = result?.response || null;
      this._form = false;
    });
  }

  // ---- rendering ----------------------------------------------------------

  _render() {
    if (!this._hass) return;
    const phones = this._phones();
    const callable = phones.filter((phone) => !phone.gateway && phone.enabled);
    if (!this._from || !callable.some((phone) => phone.number === this._from)) this._from = callable[0]?.number || "";
    const view = this._view;
    const parts = [];
    const headings = { dialer: "Dialer", phones: "Phones", live: "Live call", add: "Add phone", history: "Call history" };
    if (headings[view]) parts.push(el("div", { class: "identity" }, this.brandImage?.(), el("h2", {}, this._config.title || headings[view])));
    if (view === "combined") parts.push(this._header(phones), this._dialer(callable), this._phoneGrid(phones), this._live(), this._status(), this._createdBox(), this._addPhone());
    else if (view === "dialer") parts.push(this._dialer(callable), this._status());
    else if (view === "phones") parts.push(this._phoneGrid(phones), this._status());
    else if (view === "live") parts.push(this._live());
    else if (view === "history") parts.push(this._history(), this._status());
    else if (view === "add") parts.push(this._createdBox(), this._addPhone(true), this._status());
    else parts.push(el("p", { class: "empty" }, `Unsupported Simson card view “${view}”.`));
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("div", { class: "card" }, parts.filter(Boolean)));
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
    if (!callable.length) return el("p", { class: "empty" }, "No Simson phones yet. Finish setting up the integration, or add a phone.");
    const disabled = this._busy || !this._from || !this._to || this._from === this._to;
    return el("div", { class: "row" },
      el("label", { class: "grow" }, "From", el("select", { "aria-label": "Call from", onchange: (e) => { this._from = e.target.value; try { localStorage.setItem("simson.from", this._from); } catch {} this._render(); } },
        callable.map((phone) => el("option", { value: phone.number, selected: phone.number === this._from }, `${phone.number} ${phone.name}`.trim())))),
      el("label", { class: "grow" }, "To extension", el("input", { class: "num", value: this._to, inputmode: "numeric", placeholder: "1202", "aria-label": "Extension to call", oninput: (e) => { this._to = e.target.value.replace(/\D/g, ""); this._render(); const box = this.shadowRoot.querySelector("input.num"); box?.focus(); box?.setSelectionRange(this._to.length, this._to.length); } })),
      el("div", { class: "actions" },
        el("button", { disabled, onclick: () => this._placeCall(false) }, this._busy ? "Calling…" : "Call"),
        this._config.video !== false && el("button", { class: "video", disabled, onclick: () => this._placeCall(true), "aria-label": "Start a video call" }, "Video")),
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

  _createdBox() {
    if (!this._created) return null;
    const c = this._created;
    return el("div", { class: "ok", role: "status" },
      el("strong", {}, `Phone ${c.extension} created. The password is shown only once.`),
      el("dl", {}, [["Server", c.server], ["Port", c.port], ["Transport", c.transport], ["Username", c.username], ["Password", c.password]].filter(([, v]) => v != null).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))])),
      el("button", { class: "quiet", onclick: () => { this._created = null; this._render(); } }, "I have saved it"));
  }

  _addPhone(always = false) {
    if (!this._form && !always) return el("div", { class: "row" }, el("button", { class: "quiet", onclick: () => { this._form = true; this._render(); } }, "Add a phone"));
    return el("form", { class: "row", onsubmit: (e) => { e.preventDefault(); this._create(e.target); } },
      el("label", { class: "grow" }, "Name", el("input", { name: "name", placeholder: "Kitchen", required: true, maxlength: 200, "aria-label": "Phone name" })),
      el("label", {}, "Extension", el("input", { name: "extension", placeholder: "1204", inputmode: "numeric", pattern: "[1-9][0-9]{1,7}", required: true, "aria-label": "Extension number" })),
      el("button", { type: "submit", disabled: this._busy }, "Create"),
      !always && el("button", { type: "button", class: "quiet", onclick: () => { this._form = false; this._render(); } }, "Cancel"));
  }
}

if (!customElements.get("simson-card-impl")) customElements.define("simson-card-impl", SimsonCardImpl);
export const createCard = (brandImage) => {
  const card = document.createElement("simson-card-impl");
  card.brandImage = brandImage;
  return card;
};
