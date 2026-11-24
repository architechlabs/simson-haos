import { extension, readConfig } from "./config.js";
import { idleSnapshot, joinSession, preparePhone } from "./session.js";
import styles from "./call-card.css";

const template = document.createElement("template");
template.innerHTML = `
  <style>${styles}</style>
  <ha-card>
    <header>
      <div class="heading"><img class="brand-mark" src="${new URL("brand/icon.png", import.meta.url).href}" alt="" width="36" height="36"><div><h2 id="title"></h2><p id="identity"></p></div></div>
      <span id="state" class="state" role="status" hidden></span>
    </header>
    <section class="card-preview" id="card-preview" hidden>
      <span class="card-icon"><ha-icon id="view-icon" aria-hidden="true"></ha-icon></span>
      <p class="hint" id="preview-description"></p>
    </section>
    <section id="live-controls" hidden>
      <p class="notice" id="notice" role="status" hidden></p>
      <div class="pickup" id="pickup" role="status" hidden><ha-icon icon="mdi:phone-incoming-outline" aria-hidden="true"></ha-icon><div><strong id="pickup-title"></strong><p id="pickup-detail"></p></div></div>
      <p class="hint" id="idle-view" hidden></p>
      <form id="login">
        <label>SIP password<input id="password" type="password" required maxlength="256" autocomplete="off"></label>
        <details id="relay-settings" hidden>
          <summary>Network relay</summary>
          <label>TURN username<input id="relay-user" autocomplete="off" maxlength="256"></label>
          <label>TURN password<input id="relay-password" type="password" autocomplete="off" maxlength="256"></label>
        </details>
        <label class="choice"><input id="ring" type="checkbox" checked> Ring for incoming calls</label>
        <button class="primary" type="submit"><ha-icon icon="mdi:phone-check-outline"></ha-icon><span id="connect-label">Connect</span></button>
      </form>
      <form id="dial" hidden>
        <label>Extension<input id="number" inputmode="numeric" pattern="[1-9][0-9]{1,7}" maxlength="8" required autocomplete="off" placeholder="e.g. 201"></label>
        <div class="actions">
          <button class="primary" type="submit"><ha-icon icon="mdi:phone"></ha-icon>Audio call</button>
          <button id="video" type="button"><ha-icon icon="mdi:video-outline"></ha-icon>Video call</button>
        </div>
      </form>
      <div id="directory">
        <h3 id="contacts-title">Contacts</h3>
        <div class="directory" id="contacts" aria-label="Contacts"></div>
        <p class="hint" id="no-contacts">Add contacts in the card configuration.</p>
      </div>
      <label class="choice" id="camera-choice" hidden><input id="camera" type="checkbox"> Share my camera on video calls</label>
      <div class="call-meta" id="call-meta" hidden>
        <span class="hint" id="call-phase" role="status"></span>
        <strong id="peer"></strong>
      </div>
      <div class="media" id="media" hidden>
        <p id="video-wait">Waiting for video from the other device…</p>
        <video id="remote" class="remote audio-only" autoplay playsinline aria-label="Remote media"></video>
        <video id="local" class="local" autoplay muted playsinline aria-label="Local camera preview" hidden></video>
      </div>
      <div class="external-media" id="external-media" hidden>
        <button id="preview" type="button" hidden>Show camera</button>
        <div id="camera-entity" hidden></div>
        <div id="player-entity" hidden></div>
        <p id="media-error" class="notice" role="status" hidden></p>
      </div>
      <button id="play" type="button" hidden><ha-icon icon="mdi:volume-high"></ha-icon>Play call audio</button>
      <div class="actions" id="controls" hidden>
        <button id="answer" type="button" class="primary"><ha-icon icon="mdi:phone-incoming"></ha-icon>Answer</button>
        <button id="answer-camera" type="button"><ha-icon icon="mdi:video-outline"></ha-icon>Answer with camera</button>
        <button id="mute" type="button" aria-pressed="false">Mute</button>
        <button id="end" type="button" class="danger"><ha-icon icon="mdi:phone-hangup"></ha-icon><span>End call</span></button>
      </div>
      <details id="tones" hidden><summary>Keypad tones</summary><div class="keypad" id="keypad"></div></details>
      <button id="disconnect" type="button" hidden>Disconnect</button>
    </section>
  </ha-card>`;

const connectionLabels = { offline: "Disconnected", connecting: "Connecting", reconnecting: "Reconnecting", ready: "Ready" };
const callLabels = { dialing: "Calling", ringing: "Ringing", incoming: "Incoming call", connecting: "Answering", active: "In call", ending: "Ending call" };
const views = {
  combined: { name: "Simson calls", icon: "mdi:phone-in-talk-outline", description: "Dial, answer and see video in one card." },
  dialer: { name: "Dialer", icon: "mdi:dialpad", description: "Dial SIP extensions for audio or video calls." },
  contacts: { name: "Contacts", icon: "mdi:account-box-multiple-outline", description: "Call frequently used extensions with one tap." },
  controls: { name: "Call controls", icon: "mdi:phone-outline", description: "Answer, mute and end calls from a separate card." },
  video: { name: "Call video", icon: "mdi:video-outline", description: "Display video from SIP phones and door stations." },
  media: { name: "Door and room media", icon: "mdi:cctv", description: "Preview a Home Assistant camera or control a room media player." },
};

class SimsonCallCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).append(template.content.cloneNode(true));
    this.el = Object.fromEntries([...this.shadowRoot.querySelectorAll("[id]")].map((element) => [element.id, element]));
    this.snapshot = idleSnapshot;
    this.viewAccess = { primary: true, media: true, shareCamera: false };
    this.receive = (snapshot, shared) => this.render(snapshot, shared);
    this.el.login.addEventListener("submit", (event) => { event.preventDefault(); void this.connect(); });
    this.el.password.addEventListener("focus", preparePhone, { once: true });
    this.el.dial.addEventListener("submit", (event) => { event.preventDefault(); void this.call(false); });
    this.el.video.addEventListener("click", () => void this.call(true));
    this.el.answer.addEventListener("click", () => void this.phone?.answer(false));
    this.el["answer-camera"].addEventListener("click", () => void this.phone?.answer(true));
    this.el.mute.addEventListener("click", () => this.phone?.toggleMute());
    this.el.end.addEventListener("click", () => void this.phone?.end());
    this.el.disconnect.addEventListener("click", () => this.binding?.group.disconnect());
    this.el.camera.addEventListener("change", () => this.binding?.group.camera(this.el.camera.checked));
    this.el.play.addEventListener("click", () => void this.playMedia());
    this.el.remote.addEventListener("loadeddata", () => this.showFrame());
    this.el.remote.addEventListener("resize", () => this.showFrame());
    this.el.preview.addEventListener("click", () => {
      this.preview = !this.preview;
      this.renderExternalMedia();
    });
  }

  set hass(value) {
    const changed = this.ha?.connection !== value?.connection;
    this.ha = value;
    for (const id of ["camera-entity", "player-entity"]) {
      const card = this.el[id].firstElementChild;
      if (card) card.hass = value;
    }
    if (changed) this.watchPickup();
  }

  get phone() { return this.binding?.group.phone; }

  addKeypad() {
    if (this.el.keypad.childElementCount) return;
    for (const tone of "123456789*0#") {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = tone;
      button.setAttribute("aria-label", `Send ${tone}`);
      button.addEventListener("click", () => this.phone?.dtmf(tone));
      this.el.keypad.append(button);
    }
  }

  setConfig(input) {
    const view = views[this.constructor.view];
    if (input && typeof input === "object" && !Array.isArray(input) && Object.keys(input).every((key) => key === "type")) {
      this.leaveSession();
      this.config = undefined;
      this.preview = false;
      this.updateNotificationLink();
      this.el.title.textContent = view.name;
      this.el.identity.textContent = "Simson by Architech Labs";
      this.el["view-icon"].setAttribute("icon", view.icon);
      this.el["preview-description"].textContent = view.description;
      this.el["card-preview"].hidden = false;
      this.el["live-controls"].hidden = true;
      this.el.state.hidden = true;
      void this.renderMediaEntity("camera-entity", "");
      void this.renderMediaEntity("player-entity", "");
      return;
    }
    const config = readConfig(input, view.name);
    if (JSON.stringify(this.config) === JSON.stringify(config)) return;
    this.leaveSession();
    this.config = config;
    this.preview = false;
    this.updateNotificationLink();
    this.el.title.textContent = config.title;
    this.el.identity.textContent = `Extension ${config.extension}`;
    this.el["card-preview"].hidden = true;
    this.el["live-controls"].hidden = false;
    this.el.state.hidden = false;
    this.el["contacts-title"].hidden = this.constructor.view === "contacts";
    this.el["relay-settings"].hidden = !config.relay;
    const cards = config.contacts.map((contact) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "contact";
      const name = document.createElement("span");
      const detail = document.createElement("small");
      name.textContent = contact.name;
      detail.textContent = `${contact.extension} · ${contact.video ? "Video" : "Audio"}`;
      button.append(name, detail);
      button.addEventListener("click", () => void this.call(contact.video, contact.extension));
      return button;
    });
    this.el.contacts.replaceChildren(...cards);
    this.el.contacts.hidden = cards.length === 0;
    this.el["no-contacts"].hidden = cards.length > 0;
    this.attachSession();
    this.render();
  }

  getCardSize() { return this.config ? (this.constructor.view === "combined" ? 5 : 3) : 2; }

  static getStubConfig() { return {}; }

  static async getConfigElement() {
    if (!customElements.get("simson-v2-card-editor")) {
      const { SimsonCardEditor } = await import("./card-editor.js");
      if (!customElements.get("simson-v2-card-editor")) customElements.define("simson-v2-card-editor", SimsonCardEditor);
    }
    const editor = document.createElement("simson-v2-card-editor");
    editor.logoSrc = new URL("brand/logo.png", import.meta.url).href;
    return editor;
  }

  connectedCallback() { this.attachSession(); this.updateNotificationLink(); }
  disconnectedCallback() { this.preview = false; this.stopPickupWatch(); this.leaveSession(); this.renderExternalMedia(); }

  updateNotificationLink() {
    const params = new URLSearchParams(location.search);
    this.notificationLink = Boolean(this.config?.siteId && params.get("simson_site") === this.config.siteId &&
      params.get("simson_extension") === this.config.extension);
    const call = params.get("simson_call") ?? "";
    this.pickupID = this.notificationLink && /^[a-f0-9-]{36}$/.test(call) ? call : "";
    this.watchPickup();
  }

  stopPickupWatch() {
    const pending = this.pickupWatch;
    this.pickupWatch = null;
    this.pickupState = undefined;
    if (pending?.stop) void Promise.resolve(pending.stop()).catch(() => {});
  }

  watchPickup() {
    const connection = this.ha?.connection;
    if (!this.isConnected || !connection?.subscribeMessage || !this.pickupID || !this.viewAccess.primary) {
      if (this.pickupWatch) this.stopPickupWatch();
      return;
    }
    if (this.pickupWatch?.id === this.pickupID && this.pickupWatch.connection === connection) return;
    this.stopPickupWatch();
    const subscription = { id: this.pickupID, connection };
    this.pickupWatch = subscription;
    connection.subscribeMessage(({ call }) => {
      if (this.pickupWatch !== subscription) return;
      this.pickupState = call?.extension === this.config.extension ? call : null;
      if (this.pickupState) preparePhone();
      this.renderPickup();
    }, { type: "simson_v2/watch_pickup", site_id: this.config.siteId, call_id: subscription.id }).then((stop) => {
      if (this.pickupWatch === subscription) subscription.stop = stop;
      else void Promise.resolve(stop()).catch(() => {});
    }).catch(() => {
      if (this.pickupWatch !== subscription) return;
      this.pickupState = null;
      this.renderPickup();
    });
  }

  renderPickup() {
    const visible = this.viewAccess.primary && this.pickupID && !this.snapshot.call;
    const ringing = visible && this.pickupState;
    this.el.pickup.hidden = !visible;
    if (!visible) {
      this.el["connect-label"].textContent = "Connect";
      return;
    }
    this.el["pickup-title"].textContent = ringing ? ringing.caller : this.pickupState === null ? "Call no longer ringing" : "Checking incoming call";
    this.el["pickup-detail"].textContent = ringing ?
      this.snapshot.connection === "ready" ? "Waiting for the invitation…" : "Connect your extension to answer." : "";
    this.el["connect-label"].textContent = ringing ? "Connect for this call" : "Connect";
  }

  renderExternalMedia() {
    const config = this.config;
    if (!config || !["combined", "video", "media"].includes(this.constructor.view)) return;
    const { call } = this.snapshot;
    const onCall = Boolean(call && config.mediaPeer && call.peer === config.mediaPeer && call.phase !== "ending");
    const showCamera = this.isConnected && config.camera && (onCall || this.preview);
    this.el["external-media"].hidden = !config.camera && !config.player;
    this.el.preview.hidden = !config.camera || onCall;
    this.el.preview.textContent = this.preview ? "Hide camera" : "Show camera";
    this.el.preview.setAttribute("aria-expanded", String(Boolean(showCamera)));
    this.renderMediaEntity("camera-entity", showCamera ? config.camera : "");
    this.renderMediaEntity("player-entity", this.isConnected ? config.player : "");
  }

  async renderMediaEntity(id, entity) {
    const target = this.el[id];
    if ((target.dataset.entity ?? "") === entity) return;
    target.dataset.entity = entity;
    target.hidden = true;
    target.replaceChildren();
    if (!entity) return;
    try {
      const helpers = await window.loadCardHelpers();
      if (target.dataset.entity !== entity || !this.isConnected) return;
      const card = helpers.createCardElement(id === "camera-entity" ?
        { type: "picture-entity", entity, camera_view: "live", show_name: false, show_state: false } :
        { type: "media-control", entity });
      card.hass = this.ha;
      target.replaceChildren(card);
      target.hidden = false;
      this.el["media-error"].hidden = true;
    } catch {
      if (target.dataset.entity !== entity) return;
      delete target.dataset.entity;
      this.el["media-error"].textContent = "Home Assistant media could not load. Check that the entity is available.";
      this.el["media-error"].hidden = false;
    }
  }

  attachSession() {
    if (this.isConnected && this.config && !this.binding) {
      try {
        this.binding = joinSession(this.config, this.constructor.view, this.receive);
      } catch (error) {
        this.render({ ...idleSnapshot, message: error.message }, { primary: true, media: false, shareCamera: false });
        this.el.login.hidden = true;
      }
    }
  }

  leaveSession() {
    const binding = this.binding;
    this.binding = null;
    for (const id of ["password", "relay-user", "relay-password"]) this.el[id].value = "";
    this.render(idleSnapshot);
    binding?.leave();
  }

  async connect() {
    if (!this.config || !this.binding || this.phone) return;
    const relayUser = this.el["relay-user"].value.trim();
    const relayPassword = this.el["relay-password"].value;
    const useRelay = this.config.relay && (relayUser || relayPassword);
    if (useRelay && (!relayUser || !relayPassword)) {
      this.binding.group.report("Enter both TURN credentials to use the relay.");
      return;
    }
    const iceServers = useRelay ? [{ urls: this.config.relay, username: relayUser, credential: relayPassword }] : [];
    const password = this.el.password.value;
    this.el.password.value = "";
    this.el["relay-user"].value = "";
    this.el["relay-password"].value = "";
    await this.binding.group.connect(password, iceServers, this.el.ring.checked);
  }

  async call(video, destination = this.el.number.value.trim()) {
    try {
      if (!this.phone) return;
      await this.phone.dial(extension(destination), video, this.binding.group.shareCamera);
    } catch (error) {
      this.binding?.group.report(error instanceof Error ? error.message : "Could not start the call.");
    }
  }

  async playMedia() {
    const stream = this.el.remote.srcObject;
    if (!stream) return;
    try { await this.el.remote.play(); }
    catch {
      if (stream === this.el.remote.srcObject) this.el.play.hidden = false;
      return;
    }
    if (stream === this.el.remote.srcObject) this.el.play.hidden = true;
  }

  showFrame() {
    if (!this.snapshot.call?.video || !this.el.remote.videoWidth) return;
    this.el["video-wait"].hidden = true;
    this.el.remote.classList.remove("audio-only");
  }

  render(snapshot = this.snapshot, access = this.viewAccess) {
    const previous = this.snapshot.call?.phase;
    this.snapshot = snapshot;
    this.viewAccess = access;
    const { call, connection, message, local, remote } = snapshot;
    const view = this.constructor.view;
    const { primary, media, shareCamera } = access;
    const ready = connection === "ready";
    const incoming = call?.phase === "incoming";
    const active = call?.phase === "active";
    this.el.state.textContent = connectionLabels[connection];
    this.el.state.dataset.ready = String(ready);
    const notification = this.notificationLink && !this.pickupID && primary && !call && connection !== "ready" ? "Connect your extension to check for a call." : "";
    this.el.notice.hidden = !primary || !(message || notification);
    this.el.notice.textContent = primary ? message || notification : "";
    this.el.login.hidden = !primary || connection !== "offline";
    this.el.dial.hidden = !ready || !!call || !["combined", "dialer"].includes(view);
    this.el.camera.checked = shareCamera;
    this.el["camera-choice"].hidden = !ready || !!call || !(view === "combined" || view === "dialer" || view === "contacts" && primary);
    this.el.directory.hidden = !ready || !!call || view !== "contacts" && (view !== "combined" || this.config?.contacts.length === 0);
    this.el.disconnect.hidden = !primary || connection === "offline" || !!call;
    this.el["call-meta"].hidden = !call || !primary && !media;
    const idleMessage = connection !== "ready" && !primary ? "Connect this extension from its call controls." :
      !call && ready && view === "video" ? "Video appears here during a video call." :
      !call && ready && view === "controls" ? "Ready for incoming calls." : "";
    this.el["idle-view"].hidden = !idleMessage;
    this.el["idle-view"].textContent = idleMessage;
    this.el["call-phase"].textContent = call ? callLabels[call.phase] : "";
    this.el["call-phase"].setAttribute("aria-live", primary ? "polite" : "off");
    const knownPeer = this.config?.contacts.find((entry) => entry.extension === call?.peer);
    this.el.peer.textContent = knownPeer?.name ?? (call?.peer ? `Extension ${call.peer}` : "Private caller");
    this.el.controls.hidden = !call || !primary;
    this.el.answer.hidden = !incoming;
    this.el["answer-camera"].hidden = !incoming || !call.video;
    this.el.end.disabled = call?.phase === "ending";
    this.el.end.querySelector("span").textContent = incoming ? "Decline" : active ? "End call" : "Cancel call";
    this.el.mute.hidden = !active;
    this.el.mute.setAttribute("aria-pressed", String(call?.muted ?? false));
    this.el.mute.textContent = call?.muted ? "Unmute" : "Mute";
    this.el.tones.hidden = !active || !primary;
    if (active && primary) this.addKeypad();
    if (!active) this.el.tones.open = false;
    const visibleLocal = media && local?.getVideoTracks().length > 0;
    this.el.local.hidden = !visibleLocal;
    if (this.el.local.srcObject !== (visibleLocal ? local : null)) this.el.local.srcObject = visibleLocal ? local : null;
    const playback = media ? remote ?? null : null;
    if (this.el.remote.srcObject !== playback) {
      this.el.remote.srcObject = playback;
      this.el.remote.classList.add("audio-only");
      this.el["video-wait"].hidden = false;
      this.el.play.hidden = true;
      if (playback?.getTracks().length) void this.playMedia();
    } else if (media && active && previous !== "active") {
      void this.playMedia();
    }
    // Audio-only calls still use the same media element for remote playback.
    this.el.media.hidden = !media || !call || incoming || !call.video && !remote;
    this.el.media.classList.toggle("audio-only", !call?.video);
    this.el["video-wait"].hidden = !call?.video || this.el.remote.videoWidth > 0;
    if (primary && incoming && previous !== "incoming") this.el.answer.focus();
    this.watchPickup();
    this.renderPickup();
    this.renderExternalMedia();
  }
}

window.customCards ??= [];
for (const [type, view] of [
  ["simson-v2-call-card", "combined"],
  ["simson-v2-dialer-card", "dialer"],
  ["simson-v2-contacts-card", "contacts"],
  ["simson-v2-controls-card", "controls"],
  ["simson-v2-video-card", "video"],
  ["simson-v2-media-card", "media"],
]) {
  if (!customElements.get(type)) customElements.define(type, class extends SimsonCallCard { static view = view; });
  if (!window.customCards.some((card) => card.type === type)) {
    const { name, description } = views[view];
    window.customCards.push({ type, name: view === "combined" ? name : `Simson · ${name}`, description, preview: true });
  }
}
