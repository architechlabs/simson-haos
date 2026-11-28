import { Invitation, Inviter, Registerer, RegistererState, SessionState, UserAgent, Web } from "sip.js";
import { sipDestination } from "./config.js";

const retryDelays = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];
const audioConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
const videoConstraints = { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 20, max: 24 } };

export function supportsVideo(sdp) {
  return typeof sdp === "string" && /^m=video [1-9][0-9]*(?:\/\d+)? /m.test(sdp);
}

function browserHasH264() {
  return RTCRtpReceiver.getCapabilities("video")?.codecs.some((codec) => codec.mimeType.toLowerCase() === "video/h264");
}

function mediaOptions(video, camera) {
  return { constraints: { audio: audioConstraints, video: camera ? videoConstraints : false }, receiveVideo: video };
}

// Add a receive-only video line after SIP.js has added the microphone. This
// allows a screen without a camera to receive a video doorphone's native SIP video.
class PhoneMedia extends Web.SessionDescriptionHandler {
  async updateDirection(options) {
    await super.updateDirection(options);
    const peer = this.peerConnection;
    const videos = peer.getTransceivers().filter((item) => item.receiver.track.kind === "video");
    if (options?.receiveVideo && videos.length === 0 && peer.signalingState === "stable") {
      videos.push(peer.addTransceiver("video", { direction: "recvonly" }));
    }
    for (const item of videos) {
      if (!options?.receiveVideo) item.direction = "inactive";
      else if (!item.sender.track && item.direction !== "inactive") item.direction = "recvonly";
      // Prefer H.264 across both phone legs. Keep RTX capabilities so the
      // browser can negotiate retransmissions associated with that codec.
      const capabilities = RTCRtpReceiver.getCapabilities("video")?.codecs ?? [];
      const codecs = capabilities.filter((codec) => /^(video\/h264|video\/rtx)$/i.test(codec.mimeType));
      if (codecs.some((codec) => codec.mimeType.toLowerCase() === "video/h264")) {
        item.setCodecPreferences?.(codecs);
      }
    }
  }
}

const messages = {
  403: "This extension cannot place that call.",
  404: "That extension is unavailable.",
  408: "The call timed out.",
  480: "That extension is unavailable.",
  486: "That extension is busy.",
  488: "The devices could not agree on media. Try an audio call.",
  603: "The call was declined.",
};

export class BrowserPhone {
  constructor(config, publish, iceServers = []) {
    this.config = config;
    this.publish = publish;
    this.iceServers = iceServers;
    this.connection = "offline";
    this.call = null;
    this.retry = 0;
    this.closed = false;
    this.resumeNetwork = () => {
      if (this.connection === "reconnecting" && !this.reconnectRunning) {
        clearTimeout(this.timer);
        this.timer = undefined;
        this.reconnect(true);
      }
    };
    this.resumeVisible = () => { if (document.visibilityState === "visible") this.resumeNetwork(); };
  }

  update(values) {
    Object.assign(this, values);
    const call = this.call;
    const handler = call?.session.sessionDescriptionHandler;
    this.publish({
      connection: this.connection,
      message: this.message ?? "",
      call: call ? { phase: call.phase, peer: call.peer, video: call.video, muted: call.muted } : null,
      local: handler?.localMediaStream,
      remote: handler?.remoteMediaStream,
    });
  }

  async connect(password) {
    const uri = UserAgent.makeURI(`sip:${this.config.extension}@${this.config.registrationRealm}`);
    const rawPassword = String(password);
    if (rawPassword.length < 8 || rawPassword.length > 256 || /[\u0000-\u001f\u007f]/.test(rawPassword)) {
      throw new Error("Enter the SIP password for this extension.");
    }
    const factory = Web.defaultMediaStreamFactory();
    this.ua = new UserAgent({
      uri,
      authorizationUsername: this.config.extension,
      authorizationPassword: rawPassword,
      logConfiguration: false,
      logBuiltinEnabled: false,
      noAnswerTimeout: 45,
      transportOptions: { server: this.config.websocket, traceSip: false, connectionTimeout: 8, keepAliveInterval: 25 },
      sessionDescriptionHandlerFactory: (session) => new PhoneMedia(session.userAgent.getLogger("media"), factory, {
        iceGatheringTimeout: this.iceServers.length ? 4_000 : 1_200,
        peerConnectionConfiguration: { iceServers: this.iceServers, bundlePolicy: "balanced", rtcpMuxPolicy: "require" },
      }),
      delegate: {
        onConnect: () => { if (!this.closed && this.registerer) void this.register(); },
        onDisconnect: () => { if (!this.closed) this.reconnect(); },
        onInvite: (invite) => this.incoming(invite),
      },
    });
    this.registerer = new Registerer(this.ua, { expires: 180 });
    this.registerer.stateChange.addListener((state) => {
      if (this.closed) return;
      if (state === RegistererState.Registered) {
        clearTimeout(this.timer);
        this.timer = undefined;
        this.retry = 0;
        this.update({ connection: "ready", message: "" });
      } else if (state === RegistererState.Unregistered && this.connection === "ready") {
        this.reconnect();
      }
    });
    this.update({ connection: "connecting", message: "" });
    globalThis.addEventListener("online", this.resumeNetwork);
    document.addEventListener("visibilitychange", this.resumeVisible);
    try {
      await this.ua.start();
    } catch {
      this.reconnect();
    }
  }

  async register() {
    if (this.closed || this.registerPending) return;
    this.registerPending = true;
    this.update({ connection: "connecting", message: "" });
    try {
      await this.registerer.register({
        requestDelegate: { onReject: ({ message }) => {
          if (this.closed) return;
          if ([401, 403, 404, 407].includes(message.statusCode)) {
            void this.close("SIP login was rejected. Check the extension and password.");
          } else {
            this.reconnect();
          }
        } },
      });
    } catch {
      if (!this.closed) this.reconnect();
    } finally {
      this.registerPending = false;
    }
  }

  reconnect(immediate = false) {
    if (this.closed || this.timer) return;
    const attempt = Math.min(this.retry++, retryDelays.length - 1);
    this.update({ connection: "reconnecting", message: "Trying to restore the secure connection." });
    this.timer = setTimeout(async () => {
      this.timer = undefined;
      if (this.closed) return;
      if (navigator.onLine === false) { this.reconnect(); return; }
      this.reconnectRunning = true;
      try {
        if (!this.ua.isConnected()) await this.ua.reconnect();
        else await this.register();
      } catch {
        this.reconnect();
      } finally {
        this.reconnectRunning = false;
      }
    }, immediate ? 0 : retryDelays[attempt] * (1 + Math.random() * .2));
  }

  bind(session, phase, peer, video, options) {
    const call = { session, phase, peer, video, muted: false };
    this.call = call;
    session.sessionDescriptionHandlerOptionsReInvite = options;
    session.delegate = { onSessionDescriptionHandler: (handler) => {
      handler.remoteMediaStream.addEventListener("addtrack", () => { if (this.call === call) this.update({}); });
      handler.localMediaStream.addEventListener("addtrack", () => { if (this.call === call) this.update({}); });
      handler.peerConnection.addEventListener("connectionstatechange", () => {
        if (this.call === call && handler.peerConnection?.connectionState === "failed") {
          void this.end("The media connection failed. Check network or relay access.");
        }
      });
      this.update({});
    } };
    session.stateChange.addListener((state) => {
      if (this.call !== call) return;
      if (state === SessionState.Established) {
        call.phase = "active";
      } else if (state === SessionState.Terminated) {
        this.call = null;
      }
      this.update({});
    });
    this.update({ message: "" });
    return call;
  }

  incoming(invitation) {
    if (this.closed || this.connection !== "ready" || this.call) {
      void invitation.reject({ statusCode: 486 }).catch(() => {});
      return;
    }
    const peer = invitation.remoteIdentity.uri.user ?? "";
    const video = supportsVideo(invitation.body) && browserHasH264();
    this.bind(invitation, "incoming", peer, video, mediaOptions(video, false));
  }

  async dial(number, video, camera) {
    if (this.connection !== "ready" || this.call) return;
    const destination = sipDestination(number);
    if (destination === this.config.extension) throw new Error("Choose a different extension.");
    if (video && !browserHasH264()) throw new Error("This browser does not offer H.264 video. Try an audio call.");
    const target = UserAgent.makeURI(`sip:${destination}@${this.config.registrationRealm}`);
    const options = mediaOptions(video, video && camera);
    const session = new Inviter(this.ua, target, { sessionDescriptionHandlerOptions: options });
    const call = this.bind(session, "dialing", destination, video, options);
    try {
      await session.invite({ requestDelegate: {
        onProgress: ({ message }) => {
          if (this.call === call && message.statusCode === 180) {
            call.phase = "ringing";
            this.update({});
          }
        },
        onReject: ({ message }) => {
          if (this.call === call || !this.call) this.update({ message: messages[message.statusCode] ?? "The call could not connect." });
        },
      } });
    } catch {
      if (this.call === call) {
        await session.dispose().catch(() => {});
        this.update({ call: null, message: "Could not start the call. Check microphone and camera permissions." });
      }
    }
  }

  async answer(camera) {
    const call = this.call;
    if (call?.phase !== "incoming") return;
    call.phase = "connecting";
    this.update({});
    const options = mediaOptions(call.video, call.video && camera);
    call.session.sessionDescriptionHandlerOptionsReInvite = options;
    try {
      await call.session.accept({ sessionDescriptionHandlerOptions: options });
    } catch {
      if (this.call === call) {
        await call.session.dispose().catch(() => {});
        this.update({ call: null, message: "Could not answer. Check microphone and camera permissions." });
      }
    }
  }

  async end(message = "") {
    const call = this.call;
    if (!call || call.phase === "ending") return;
    call.phase = "ending";
    this.update({ message });
    try {
      const { session } = call;
      if (session.state === SessionState.Established) await session.bye();
      else if (session instanceof Inviter) await session.cancel();
      else if (session instanceof Invitation) await session.reject({ statusCode: 603 });
    } catch {
      await call.session.dispose().catch(() => {});
      if (this.call === call) this.update({ call: null, message: message || "The call connection closed." });
    }
  }

  toggleMute() {
    const call = this.call;
    if (call?.phase !== "active") return;
    call.muted = !call.muted;
    for (const track of call.session.sessionDescriptionHandler.localMediaStream.getAudioTracks()) track.enabled = !call.muted;
    this.update({});
  }

  dtmf(tone) {
    if (this.call?.phase !== "active" || !/^[0-9*#]$/.test(tone)) return;
    if (!this.call.session.sessionDescriptionHandler.sendDtmf(tone, { duration: 160, interToneGap: 90 })) {
      this.update({ message: "The active call did not negotiate keypad tones." });
    }
  }

  async close(message = "") {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.timer);
    globalThis.removeEventListener("online", this.resumeNetwork);
    document.removeEventListener("visibilitychange", this.resumeVisible);
    this.update({ call: null, connection: "offline", message });
    await this.ua?.stop().catch(() => {});
  }
}
