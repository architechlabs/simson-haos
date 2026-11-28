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
.setup{display:grid;gap:8px}.setup a{justify-self:start;color:var(--primary-color);font-weight:600;padding-block:8px}
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

const inventories = new WeakMap();
function inventory(states) {
  if (!states) return { locations: [], phones: [] };
  if (!inventories.has(states)) {
    const locations = [];
    const phones = [];
    for (const [entity, state] of Object.entries(states)) {
      const attrs = state.attributes;
      if (entity.startsWith("sensor.") && attrs?.simson_voice && attrs.config_entry_id) locations.push(attrs);
      if (entity.startsWith("binary_sensor.") && attrs?.simson_extension) {
        phones.push({ entryID: attrs.config_entry_id, number: String(attrs.simson_extension), name: attrs.name || "",
          gateway: !!attrs.gateway, enabled: attrs.enabled !== false, video: attrs.video === true,
          online: state.state === "on" ? true : state.state === "off" ? false : null });
      }
    }
    phones.sort((a, b) => a.number.localeCompare(b.number, undefined, { numeric: true }));
    inventories.set(states, { locations, phones });
  }
  return inventories.get(states);
}

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
    if (next.browser !== this._config.browser || next.view !== this._config.view ||
        next.mode !== this._config.mode || next.config_entry_id !== this._config.config_entry_id) {
      this._browserCard = null;
      this._browserFailed = false;
      this._browserKey = null;
      this._selectedEntry = "";
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
      if (value?.states !== previousStates) this._scheduleInventoryRefresh();
    } else if (first) {
      this._render();
    } else if (value?.states !== previousStates && (this._hasPhoneControls() || this._usesBrowser())) {
      this._scheduleInventoryRefresh();
    }
  }

  _scheduleInventoryRefresh() {
    if (this._inventoryRefreshQueued) return;
    this._inventoryRefreshQueued = true;
    queueMicrotask(() => {
      this._inventoryRefreshQueued = false;
      if (!this.isConnected) return;
      if (this._usesBrowser()) this._renderBrowserPhone();
      else this._refreshPhoneInventory();
    });
  }

  _hasPhoneControls() { return ["combined", "dialer", "phones"].includes(this._view); }
  _usesBrowser() {
    if (this._view === "live") {
      const locations = inventory(this._hass?.states).locations;
      return this._config.mode !== "relay" && Boolean(this._browserCard || this._config.browser || locations.some((site) =>
        site.sip_wss_port && site.browser_endpoint_ready &&
        (!this._config.config_entry_id || site.config_entry_id === this._config.config_entry_id)));
    }
    return ["browser", "controls", "video"].includes(this._view) || ["combined", "dialer"].includes(this._view) &&
      (this._config.browser || this._config.mode !== "relay");
  }

  _refreshPhoneInventory() {
    const phones = this._phones();
    const changes = JSON.stringify(phones);
    if (changes !== this._phoneInventory) this._render(phones);
  }
  connectedCallback() { this._render(); }
  disconnectedCallback() {
    this._unmount?.();
    this._unmount = null;
    this._slot = null;
  }

  // ---- discovery ----------------------------------------------------------

  _phones(entryID = this._config.config_entry_id) {
    return inventory(this._hass?.states).phones.filter((phone) => !entryID || phone.entryID === entryID);
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
    if (this._usesBrowser()) {
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
    else if (view === "phones") parts.push(this._phoneGrid(callable), this._status());
    else if (view === "live") parts.push(this._live());
    else if (view === "history") parts.push(this._history(), this._status());
    else if (view === "add") parts.push(el("p", { class: "note" }, "Manage SIP extensions in the Simson portal."));
    else parts.push(el("p", { class: "empty" }, `Unsupported Simson card view “${view}”.`));
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("div", { class: "card" }, parts.filter(Boolean)));
  }

  _renderBrowserPhone() {
    const entryID = this._config.config_entry_id || this._selectedEntry;
    const locations = inventory(this._hass.states).locations.filter((site) => !entryID || site.config_entry_id === entryID);
    const site = locations.length === 1 ? locations[0] : null;
    let config = this._config.browser;
    if (!config) {
      if (locations.length > 1) {
        const select = el("select", { "aria-label": "Simson location", onchange: (event) => {
          this._selectedEntry = event.target.value;
          this._renderBrowserPhone();
        } }, el("option", { value: "" }, "Choose a location"),
        locations.map((item) => el("option", { value: item.config_entry_id }, item.site_name || item.sip_realm || "Simson location")));
        this._browserSetup("Choose the location this Home Assistant screen should call from.", select);
        return;
      }
      if (!site) {
        this._browserSetup("Connect a Simson location in Home Assistant to set up this phone.");
        return;
      }
      const extension = site.browser_extension || "100";
      const realm = site.browser_realm || site.sip_realm;
      if (!site.browser_endpoint_ready || !site.sip_wss_port || !realm) {
        if (this._browserCard) return;
        const requirements = [];
        if (!site.browser_endpoint_ready) requirements.push(`Create or enable SIP extension ${extension} in this Simson location.`);
        if (!site.sip_wss_port || !realm) requirements.push("Enable the secure SIP WebSocket listener on the Simson voice server.");
        if (!window.isSecureContext) requirements.push("Open Home Assistant using its HTTPS address to use this screen’s microphone and video.");
        this._browserSetup("Finish setting up this screen’s phone.", null, requirements);
        return;
      }
      config = { extension, realm, registration_realm: site.browser_registration_realm || realm,
        websocket: `wss://${realm}:${site.sip_wss_port}`,
        site_id: site.site_id, keep_connected: true, video_enabled: site.browser_video === true, title: this._config.title || "Simson phone" };
    }
    const directory = { phones: site ? this._phones(site.config_entry_id).filter((phone) => phone.enabled && !phone.gateway && phone.number !== String(config.extension)) : [],
      routes: site && String(config.extension) === site.browser_extension ? site.outbound_routes || [] : [] };
    const key = JSON.stringify(config);
    if (this._browserCard) {
      if (key === this._browserKey) {
        this._browserCard.hass = this._hass;
        this._browserCard.directoryData = directory;
        return;
      }
      this._browserCard = null;
      this._browserFailed = false;
    }
    if (this._browserKey !== key) this._browserFailed = false;
    this._browserKey = key;
    if (!this._browserLoading && !this._browserFailed) void this._loadBrowserPhone(config, key, directory);
  }

  _browserSetup(message, action, requirements = []) {
    const key = JSON.stringify([message, requirements, action ? [...action.options].map(option => [option.value, option.textContent]) : null]);
    if (this._setupMessage === key && this.shadowRoot.querySelector(".setup")) return;
    this._browserCard = null;
    this._browserKey = null;
    this._browserFailed = false;
    this._setupMessage = key;
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("ha-card", { class: "card setup" },
      el("div", { class: "identity" }, this.brandImage?.(), el("h2", {}, this._config.title || "Simson phone")),
      el("p", { class: "note" }, message),
      requirements.length > 0 && el("ul", { class: "note" }, requirements.map((requirement) => el("li", {}, requirement))),
      action || el("a", { href: "https://simson.architechlabs.in/dashboard/", target: "_blank", rel: "noopener noreferrer" }, "Open Simson dashboard")));
  }

  async _loadBrowserPhone(config, key, directory) {
    const path = new URL("./browser-sip/simson-call-card.js", import.meta.url);
    if (this._browserFailures) path.searchParams.set("retry", Date.now());
    this._browserLoading = true;
    this.shadowRoot.replaceChildren(el("style", {}, STYLE), el("p", { class: "empty", role: "status" }, "Opening browser phone…"));
    try {
      if (!customElements.get("simson-v2-call-card")) await import(path.href);
      if (key !== this._browserKey || !this.isConnected) return;
      const view = this._view === "live" ? "controls" : this._view;
      const variant = ["dialer", "controls", "video"].includes(view) ? `simson-v2-${view}-card` : "simson-v2-call-card";
      const tag = customElements.get(variant) ? variant : "simson-v2-call-card";
      const card = document.createElement(tag);
      card.setConfig({ ...config, type: `custom:${tag}` });
      card.hass = this._hass;
      card.directoryData = directory;
      this._browserCard = card;
      this.shadowRoot.replaceChildren(card);
    } catch (error) {
      if (key !== this._browserKey) return;
      this._browserFailed = true;
      this._browserFailures = (this._browserFailures || 0) + 1;
      const message = customElements.get("simson-v2-call-card") ? error.message :
        "The browser phone did not load. Retry to download its files.";
      this.shadowRoot.replaceChildren(el("style", {}, STYLE),
        el("div", { class: "card" }, el("p", { role: "alert", class: "note" }, message),
          el("button", { type: "button", class: "quiet", onclick: () => { this._browserFailed = false; this._renderBrowserPhone(); } }, "Retry")));
    } finally {
      this._browserLoading = false;
      if (key !== this._browserKey && this.isConnected) this._render();
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
