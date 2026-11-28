const extensionPattern = /^[1-9][0-9]{1,7}$/;
const realmPattern = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const sitePattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function mediaEntity(value = "", domain) {
  if (value === "") return value;
  if (typeof value !== "string" || !new RegExp(`^${domain}\\.[a-z0-9_]{1,120}$`).test(value)) {
    throw new Error(`Choose a Home Assistant ${domain} entity.`);
  }
  return value;
}

export function extension(value) {
  const result = typeof value === "number" && Number.isSafeInteger(value) ? String(value) : value;
  if (typeof result !== "string" || !extensionPattern.test(result)) {
    throw new Error("Enter a SIP extension with two to eight digits.");
  }
  return result;
}

const routePattern = /^(?:[1-9][0-9]{1,7}|\*[0-9]{2,23})$/;
const gatewayPrefixPattern = /^(?:[0-9]{1,4}|\*[0-9]{1,3}|\*86[0-9]{4})$/;
const outsidePattern = /^(?:\+[1-9][0-9]{3,14}|[0-9]{4,17})$/;
const dialModes = new Set(["auto", "extension", "route", "outside"]);

export function dialDestination(value, mode = "auto", gatewayPrefix = "") {
  if (!dialModes.has(mode)) throw new Error("Choose a dial mode.");
  const dial = typeof value === "string" ? value.trim() : String(value);
  if (mode === "extension") return extension(dial);
  if (mode === "outside") {
    if (!gatewayPrefixPattern.test(gatewayPrefix)) throw new Error("Configure a carrier access prefix first.");
    if (!outsidePattern.test(dial)) throw new Error("Enter a phone number, including + and country code when needed.");
    return gatewayPrefix + dial;
  }
  if (!routePattern.test(dial)) throw new Error("Enter a SIP extension or a configured route code.");
  return dial;
}

export function outboundRoutes(items = [], legacyPrefix = "") {
  if (!Array.isArray(items) || items.length > 160) throw new Error("Invalid outbound routes.");
  const routes = new Map();
  for (const item of items) {
    if (!item || typeof item.prefix !== "string" || !gatewayPrefixPattern.test(item.prefix)) {
      throw new Error("Use an outbound dial code configured in Simson.");
    }
    routes.set(item.prefix, Object.freeze({ prefix: item.prefix, name: label(item.name, item.prefix) }));
  }
  if (legacyPrefix && !routes.has(legacyPrefix)) routes.set(legacyPrefix, { prefix: legacyPrefix, name: "Carrier" });
  return [...routes.values()];
}

export function sipDestination(value) {
  if (typeof value !== "string" || !/^(?:[1-9][0-9]{1,7}|\*[0-9]{2,23}|(?:[0-9]{1,4}|\*[0-9]{1,3}|\*86[0-9]{4})(?:\+[1-9][0-9]{3,14}|[0-9]{4,17}))$/.test(value)) {
    throw new Error("Enter a valid SIP dial string.");
  }
  return value;
}

function label(value, fallback) {
  if (value === undefined) return fallback;
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 80 || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error("Use a name between 1 and 80 characters.");
  }
  return value.trim();
}

export function readConfig(config, defaultTitle = "Simson calls") {
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new Error("Configure a Simson location and extension for this card.");
  }
  if ("password" in config || "sip_password" in config || "ice_servers" in config) {
    throw new Error("Enter SIP and relay credentials in the card when connecting.");
  }
  if (typeof config.realm !== "string" || config.realm.length > 253 || !realmPattern.test(config.realm)) {
    throw new Error("Set the SIP realm from the Simson location.");
  }
  if (typeof config.websocket !== "string" || config.websocket.length > 300) {
    throw new Error("Set the secure SIP WebSocket from the Simson location.");
  }
  let websocket;
  try { websocket = new URL(config.websocket); } catch { throw new Error("Enter a valid WSS address."); }
  if (websocket.protocol !== "wss:" || websocket.hostname !== config.realm ||
      websocket.username || websocket.password || websocket.search || websocket.hash ||
      !/^\/(?:[a-zA-Z0-9_/-]{1,80})?$/.test(websocket.pathname)) {
    throw new Error("The WebSocket must use WSS and match the configured SIP realm.");
  }
  const local = extension(config.extension);
  const registrationRealm = config.registration_realm ?? config.realm;
  if (registrationRealm !== config.realm && (typeof registrationRealm !== "string" ||
      !/^s-[a-z0-9]{3,10}\.vipsy\.in$/.test(registrationRealm))) {
    throw new Error("Use the location’s assigned SIP registration realm.");
  }
  if (config.keep_connected !== undefined && typeof config.keep_connected !== "boolean") throw new Error("Keep connected must be true or false.");
  const siteId = config.site_id ?? "";
  if (typeof siteId !== "string" || siteId && !sitePattern.test(siteId)) throw new Error("Use the Simson location ID.");
  const relay = config.relay ?? "";
  const relayPort = typeof relay === "string" && relay.match(/^turns?:[a-zA-Z0-9.-]+:(\d{2,5})(?:\?transport=(?:udp|tcp))?$/)?.[1];
  if (relay !== "" && (!relayPort || Number(relayPort) < 1 || Number(relayPort) > 65535)) {
    throw new Error("Use a TURN or TURNS address with a port.");
  }
  const gatewayPrefix = config.gateway_prefix ?? "";
  if (gatewayPrefix !== "" && (typeof gatewayPrefix !== "string" || !gatewayPrefixPattern.test(gatewayPrefix))) {
    throw new Error("Use the carrier access prefix configured in Simson.");
  }
  if (config.video_enabled !== undefined && typeof config.video_enabled !== "boolean") throw new Error("Video availability must be true or false.");
  const routes = outboundRoutes(config.outbound_routes, gatewayPrefix);
  const contacts = config.contacts ?? [];
  if (!Array.isArray(contacts) || contacts.length > 64) throw new Error("Add up to 64 contacts.");
  const seen = new Set([local]);
  const directory = contacts.map((item) => {
    const mode = item?.mode ?? "extension";
    const number = dialDestination(item?.extension, mode, gatewayPrefix);
    if (mode === "outside" && item.video) throw new Error("Outside contacts use audio only.");
    if (seen.has(number)) throw new Error("Each contact must have a unique extension.");
    seen.add(number);
    if (item.video !== undefined && typeof item.video !== "boolean") throw new Error("Set video to true or false.");
    return Object.freeze({ extension: number, name: label(item.name, number), video: item.video === true });
  });
  return Object.freeze({
    realm: config.realm,
    registrationRealm,
    websocket: websocket.href,
    extension: local,
    keepConnected: config.keep_connected === true,
    siteId,
    camera: mediaEntity(config.camera_entity, "camera"),
    player: mediaEntity(config.media_player_entity, "media_player"),
    mediaPeer: config.media_extension === undefined ? "" : extension(config.media_extension),
    relay,
    gatewayPrefix,
    routes: Object.freeze(routes),
    videoEnabled: config.video_enabled !== false,
    title: label(config.title, defaultTitle),
    contacts: Object.freeze(directory),
  });
}
