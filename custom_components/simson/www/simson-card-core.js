// Simson card: the interface. Loaded lazily by simson-card.js.
// Calls are placed by Simson between the two phones, so audio goes phone to phone
// over the voice service with no browser handshake to wait for.

const STYLE = `
:host{display:block}
ha-card,.card{display:block;padding:16px;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color);box-shadow:var(--ha-card-box-shadow,none);font-family:var(--paper-font-body1_-_font-family,system-ui)}
h2{margin:0 0 12px;font-size:18px;font-weight:600}
h3{margin:16px 0 8px;font-size:13px;font-weight:600;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.04em}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.grow{flex:1;min-width:120px}
select,input{box-sizing:border-box;min-height:40px;padding:0 10px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit}
button{min-height:40px;padding:0 16px;border:0;border-radius:8px;background:var(--primary-color);color:var(--text-primary-color,#fff);font:inherit;font-weight:600;cursor:pointer}
button.quiet{background:transparent;color:var(--primary-text-color);border:1px solid var(--divider-color)}
button.danger{background:var(--error-color,#c0392b)}
button:disabled{opacity:.5;cursor:not-allowed}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
.phones{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.phone{display:flex;align-items:center;gap:8px;padding:10px 12px;text-align:left;background:var(--secondary-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);font-weight:500}
.phone small{display:block;color:var(--secondary-text-color);font-weight:400}
.dot{flex:none;width:10px;height:10px;border-radius:50%;background:var(--disabled-text-color,#9e9e9e)}
.dot.on{background:var(--success-color,#2e7d32)}.dot.off{background:var(--error-color,#c0392b)}
.live{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--divider-color);border-radius:8px;margin-bottom:6px}
.note{margin:8px 0 0;font-size:13px;color:var(--secondary-text-color)}
.error{margin:8px 0 0;padding:8px 10px;border-radius:8px;background:color-mix(in srgb,var(--error-color,#c0392b) 14%,transparent);color:var(--primary-text-color);font-size:13px}
.ok{margin:8px 0 0;padding:8px 10px;border-radius:8px;background:color-mix(in srgb,var(--success-color,#2e7d32) 16%,transparent);font-size:13px}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:8px 0}dt{color:var(--secondary-text-color)}dd{margin:0;font-family:var(--code-font-family,monospace);user-select:all}
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
    this._hass = null;
    this._busy = false;
    this._message = null;
    this._created = null;
    this._form = false;
    this._from = localStorage.getItem("simson.from") || "";
    this._to = "";
  }

  setConfig(config) { this._config = config || {}; this._render(); }
  set hass(value) { this._hass = value; this._render(); }

  // ---- discovery ----------------------------------------------------------

  _phones() {
    const states = this._hass?.states || {};
    return Object.values(states)
      .filter((state) => state.attributes?.simson_extension && state.entity_id.startsWith("binary_sensor."))
      .map((state) => ({ number: String(state.attributes.simson_extension), name: state.attributes.name || "", gateway: !!state.attributes.gateway, enabled: state.attributes.enabled !== false, online: state.state === "on" ? true : state.state === "off" ? false : null }))
      .sort((a, b) => a.number.localeCompare(b.number, undefined, { numeric: true }));
  }

  _liveCalls() {
    const states = this._hass?.states || {};
    const sensor = Object.values(states).find((state) => state.attributes?.simson_calls);
    return sensor?.attributes?.calls || [];
  }

  // ---- actions ------------------------------------------------------------

  async _run(task) {
    if (this._busy) return;
    this._busy = true;
    this._message = null;
    this._render();
    try {
      await task();
    } catch (error) {
      this._message = { kind: "error", text: error?.message || "Simson could not do that." };
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _call() {
    return this._run(async () => {
      await this._hass.callService("simson", "call", { from_extension: this._from, to_extension: this._to });
      this._message = { kind: "ok", text: `Calling ${this._to}. Both phones will ring.` };
    });
  }

  _hangup(id) {
    return this._run(() => this._hass.callService("simson", "hangup", { call_id: id }));
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

    const root = el("div", { class: "card" },
      el("h2", {}, this._config.title || "Simson"),
      !phones.length && el("p", { class: "note" }, "No Simson phones found yet. Finish setting up the Simson integration, or add a phone below."),
      phones.length > 0 && this._callSection(callable),
      this._liveSection(),
      phones.length > 0 && el("h3", {}, "Phones"),
      phones.length > 0 && el("div", { class: "phones" }, phones.map((phone) => el("button", { class: "phone", disabled: phone.gateway || !phone.enabled || this._busy, onclick: () => { this._to = phone.number; this._render(); }, title: phone.online === null ? "Status unknown" : phone.online ? "Online" : "Offline" },
        el("span", { class: `dot ${phone.online === true ? "on" : phone.online === false ? "off" : ""}` }),
        el("span", {}, phone.number, el("small", {}, phone.gateway ? "Carrier gateway" : phone.name || " ")))),
      ),
      this._message && el("div", { class: this._message.kind, role: this._message.kind === "error" ? "alert" : "status" }, this._message.text),
      this._createdSection(),
      this._formSection(),
    );
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), root);
  }

  _callSection(callable) {
    const disabled = this._busy || !this._from || !this._to || this._from === this._to;
    return el("div", { class: "row" },
      el("label", { class: "grow" }, "From", el("select", { "aria-label": "Call from", onchange: (e) => { this._from = e.target.value; localStorage.setItem("simson.from", this._from); this._render(); } },
        callable.map((phone) => el("option", { value: phone.number, selected: phone.number === this._from }, `${phone.number} ${phone.name}`.trim())))),
      el("label", { class: "grow" }, "To extension", el("input", { value: this._to, inputmode: "numeric", placeholder: "1202", "aria-label": "Extension to call", oninput: (e) => { this._to = e.target.value.replace(/\D/g, ""); this._render(); } })),
      el("button", { disabled, onclick: () => this._call() }, this._busy ? "Calling…" : "Call"),
    );
  }

  _liveSection() {
    const calls = this._liveCalls();
    if (!calls.length) return null;
    return el("div", {}, el("h3", {}, "Live calls"), calls.map((call) => el("div", { class: "live" },
      el("span", {}, `${call.phase === "active" ? "In call" : "Ringing"} · started ${new Date(call.started_at).toLocaleTimeString()}`),
      el("button", { class: "danger", disabled: this._busy, onclick: () => this._hangup(call.id) }, "Hang up"))));
  }

  _createdSection() {
    if (!this._created) return null;
    const c = this._created;
    return el("div", { class: "ok", role: "status" },
      el("strong", {}, `Phone ${c.extension} created. The password is shown only once.`),
      el("dl", {}, [["Server", c.server], ["Port", c.port], ["Transport", c.transport], ["Username", c.username], ["Password", c.password]].filter(([, v]) => v != null).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, String(v))])),
      el("button", { class: "quiet", onclick: () => { this._created = null; this._render(); } }, "I have saved it"));
  }

  _formSection() {
    if (!this._form) return el("div", { class: "row", style: "margin-top:12px" }, el("button", { class: "quiet", onclick: () => { this._form = true; this._render(); } }, "Add a phone"));
    const form = el("form", { class: "row", style: "margin-top:12px", onsubmit: (e) => { e.preventDefault(); this._create(form); } },
      el("input", { name: "name", class: "grow", placeholder: "Name, e.g. Kitchen", required: true, maxlength: 200, "aria-label": "Phone name" }),
      el("input", { name: "extension", placeholder: "Extension", inputmode: "numeric", pattern: "[1-9][0-9]{1,7}", required: true, "aria-label": "Extension number" }),
      el("button", { type: "submit", disabled: this._busy }, "Create"),
      el("button", { type: "button", class: "quiet", onclick: () => { this._form = false; this._render(); } }, "Cancel"));
    return form;
  }
}

if (!customElements.get("simson-card-impl")) customElements.define("simson-card-impl", SimsonCardImpl);
export const createCard = () => document.createElement("simson-card-impl");
