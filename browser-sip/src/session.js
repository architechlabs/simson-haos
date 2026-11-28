const sessions = new Map();
export const idleSnapshot = Object.freeze({ connection: "offline", call: null, message: "" });
let phoneModule;
let moduleFailures = 0;

function loadPhone() {
  if (!phoneModule) {
    const url = new URL("./chunks/browser-phone.js", import.meta.url);
    phoneModule = (moduleFailures ? import(url.href + "?retry=" + moduleFailures) : import("./browser-phone.js"))
      .catch((error) => {
        moduleFailures += 1;
        phoneModule = undefined;
        throw error;
      });
  }
  return phoneModule;
}

export function preparePhone() { void loadPhone().catch(() => {}); }

function keyFor(config) {
  return JSON.stringify([location.origin, config.registrationRealm ?? config.realm, config.extension]);
}

export function joinSession(config, view, listener) {
  const key = keyFor(config);
  let group = sessions.get(key);
  if (group && (group.config.websocket !== config.websocket || group.config.relay !== config.relay)) {
    if (group.listeners.size) throw new Error("Use the same WebSocket and relay settings on cards that share an extension.");
    clearTimeout(group.releaseTimer);
    group.disconnect();
    group = null;
  }
  if (!group) {
    group = new SessionGroup(config, () => sessions.delete(key));
    sessions.set(key, group);
  }
  clearTimeout(group.releaseTimer);
  group.listeners.set(listener, { view, keepConnected: config.keepConnected === true });
  group.keepConnected = [...group.listeners.values()].some((participant) => participant.keepConnected);
  group.publish();
  return {
    group,
    leave() {
      group.listeners.delete(listener);
      if (group.listeners.size) {
        group.keepConnected = [...group.listeners.values()].some((participant) => participant.keepConnected);
        group.publish();
      } else group.releaseWhenIdle();
    },
  };
}

class SessionGroup {
  constructor(config, remove) {
    this.config = config;
    this.remove = remove;
    this.listeners = new Map();
    this.snapshot = idleSnapshot;
    this.shareCamera = false;
    this.keepConnected = false;
  }

  releaseWhenIdle() {
    clearTimeout(this.releaseTimer);
    this.releaseTimer = setTimeout(() => {
      if (this.listeners.size) return;
      if (this.keepConnected && (this.phone || this.connectAttempt)) return;
      this.disconnect();
      this.remove();
    }, 350);
  }

  publish(snapshot = this.snapshot) {
    const previous = this.snapshot;
    this.snapshot = snapshot;
    if (previous.connection !== snapshot.connection || previous.call?.phase !== snapshot.call?.phase ||
        previous.call?.muted !== snapshot.call?.muted) {
      globalThis.window?.dispatchEvent(new CustomEvent("simson:browser_call", { detail: Object.freeze({
        extension: this.config.extension, site_id: this.config.siteId || null,
        connection: snapshot.connection, phase: snapshot.call?.phase ?? null,
        video: snapshot.call?.video === true, muted: snapshot.call?.muted === true,
      }) }));
    }
    this.setRinging(snapshot.call?.phase === "incoming");
    const participants = [...this.listeners];
    const primary = participants.find(([, participant]) => participant.view === "controls") ??
      participants.find(([, participant]) => participant.view === "combined") ?? participants[0];
    const media = participants.find(([, participant]) => participant.view === "video") ?? primary;
    for (const [listener] of participants) {
      listener(snapshot, { primary: listener === primary?.[0], media: listener === media?.[0], shareCamera: this.shareCamera });
    }
  }

  report(message) { this.publish({ ...this.snapshot, message }); }

  camera(enabled) {
    if (this.shareCamera === enabled) return;
    this.shareCamera = enabled;
    this.publish();
  }

  async connect(password, iceServers, ring) {
    if (this.phone || this.connectAttempt) return;
    if (!globalThis.isSecureContext || !navigator.mediaDevices?.getUserMedia || !globalThis.RTCPeerConnection) {
      this.report("Open Home Assistant over HTTPS to use microphone and video.");
      return;
    }
    if (ring && globalThis.AudioContext) {
      try {
        this.audio = new AudioContext();
        void this.audio.resume().catch(() => {});
      } catch { this.audio = null; }
    }
    const attempt = {};
    this.connectAttempt = attempt;
    this.publish({ ...idleSnapshot, connection: "connecting" });
    let BrowserPhone;
    try {
      ({ BrowserPhone } = await loadPhone());
    } catch {
      if (this.connectAttempt !== attempt) return;
      this.connectAttempt = null;
      this.releaseAudio();
      this.publish({ ...idleSnapshot, message: "The phone module could not load. Connect again to retry." });
      if (!this.listeners.size) this.releaseWhenIdle();
      return;
    }
    if (this.connectAttempt !== attempt) return;
    this.connectAttempt = null;
    const phone = new BrowserPhone(this.config, (snapshot) => {
      if (this.phone !== phone) return;
      if (phone.closed) {
        this.phone = null;
        this.releaseAudio();
        if (!this.listeners.size) this.releaseWhenIdle();
      }
      this.publish(snapshot);
    }, iceServers);
    this.phone = phone;
    try {
      await phone.connect(password);
    } catch {
      await phone.close("Check the SIP password and try connecting again.");
    }
  }

  disconnect() {
    this.connectAttempt = null;
    const phone = this.phone;
    this.phone = null;
    if (phone) void phone.close();
    this.shareCamera = false;
    this.releaseAudio();
    this.publish(idleSnapshot);
  }

  releaseAudio() {
    this.setRinging(false);
    if (this.audio) void this.audio.close().catch(() => {});
    this.audio = null;
  }

  setRinging(ringing) {
    if (!ringing) {
      clearInterval(this.ringer);
      this.ringer = undefined;
      return;
    }
    if (this.ringer || !this.audio) return;
    const play = () => {
      if (this.audio?.state !== "running") return;
      const begin = this.audio.currentTime;
      for (const offset of [0, 0.23]) {
        const oscillator = this.audio.createOscillator();
        const gain = this.audio.createGain();
        oscillator.frequency.value = 520;
        gain.gain.setValueAtTime(0.0001, begin + offset);
        gain.gain.exponentialRampToValueAtTime(0.08, begin + offset + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.0001, begin + offset + 0.17);
        oscillator.connect(gain).connect(this.audio.destination);
        oscillator.start(begin + offset);
        oscillator.stop(begin + offset + 0.18);
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
      }
    };
    play();
    this.ringer = setInterval(play, 3_000);
  }
}
