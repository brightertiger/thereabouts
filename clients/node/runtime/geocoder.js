import fs from "node:fs";
import path from "node:path";
import { wasm } from "./wasm.js";
import { directory, installed, FAMILIES } from "./store.js";
import {
  atPack,
  ClosedGeocoderError,
  DataNotInstalledError,
  PackNotFoundError,
  IncompatibleDataError,
  convert,
} from "./errors.js";
export function freeze(value) {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
// Preserve invalid optional numbers through JSON: null would erase them.
const invalidNumber = Object.freeze({ __thereabouts_invalid_number__: true });
function coordinateValue(value, key = "", frame, depth = 0) {
  if (depth > 16) return invalidNumber;
  if (key === "cell") {
    if (typeof value === "number") return invalidNumber;
    if (typeof value === "bigint") {
      if (value < 0n || value > 0xffffffffffffffffn) return invalidNumber;
      const hex = value.toString(16);
      // S2 tokens are right-padded when decoded; preserve all 64 integer bits.
      return frame === "s2" ? hex.padStart(16, "0") : hex;
    }
  }
  if (typeof value === "number")
    return Number.isFinite(value) ? value : invalidNumber;
  if (value === null || typeof value === "string") return value;
  if (Array.isArray(value))
    return value.map((item) => coordinateValue(item, "", frame, depth + 1));
  if (value && typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null)
      return invalidNumber;
    return Object.fromEntries(
      Object.entries(value).map(([name, item]) => [
        name,
        coordinateValue(item, name, value.frame, depth + 1),
      ]),
    );
  }
  return invalidNumber;
}
function coordinateRequest(point) {
  if (
    !point ||
    typeof point !== "object" ||
    Array.isArray(point) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(point))
  )
    throw new TypeError("Use a named coordinate object with an explicit frame");
  return JSON.stringify(coordinateValue(point));
}
function coordinateEvidence(options) {
  if (!options || typeof options !== "object" || Array.isArray(options))
    throw new TypeError("Query options must be an object");
  for (const key of Object.keys(options))
    if (key !== "evidence")
      throw new TypeError(`Unknown reversePoint option: ${key}`);
  const { evidence = false } = options;
  if (typeof evidence !== "boolean")
    throw new TypeError("evidence must be boolean");
  return evidence;
}
const families = {
  h3: "core",
  geocode: "core",
  postal: "postal",
  airport: "airports",
  locode: "locode",
  phone: "phone",
  ip: "ip",
  plate: "plates",
};
export class Geocoder {
  #module;
  #paths;
  #handles = new Map();
  #closed = false;
  #verify;
  constructor(module, paths, verify) {
    this.#module = module;
    this.#paths = paths;
    this.#verify = verify;
  }
  static async open({ dataDir, pack, packs, verify = false } = {}) {
    if (pack && packs) throw new TypeError("Use pack or packs");
    const module = await wasm(),
      paths = {};
    if (pack) {
      const filename = path.resolve(pack);
      if (!fs.existsSync(filename))
        throw new PackNotFoundError(`Pack not found: ${filename}`);
      try {
        const info = JSON.parse(module.packInfo(filename, false));
        paths[info.family] = filename;
      } catch (e) {
        throw atPack(e, filename, "core");
      }
    } else if (packs) {
      for (const [name, filename] of Object.entries(packs)) {
        if (!FAMILIES.includes(name))
          throw new TypeError(`Unknown pack family: ${name}`);
        paths[name] = path.resolve(filename);
      }
    } else {
      const root = await directory(dataDir);
      for (const name of FAMILIES) {
        try {
          paths[name] = await installed(root, name);
        } catch (e) {
          if (!(e instanceof DataNotInstalledError)) throw e;
        }
      }
    }
    if (!Object.keys(paths).length) throw new DataNotInstalledError();
    let version;
    for (const [name, filename] of Object.entries(paths)) {
      try {
        const info = JSON.parse(module.packInfo(filename, false));
        if (
          info.family !== name ||
          (version !== undefined && version !== info.data_version)
        )
          throw new IncompatibleDataError(
            "Selected pack family or dataset version differs",
          );
        version = info.data_version;
      } catch (e) {
        throw atPack(e, filename, name);
      }
    }
    const geo = new Geocoder(module, paths, verify);
    try {
      // Explicit pack selections retain handles from open. Store families stay lazy
      // unless the caller requested eager full verification of the entire selection.
      if (pack || packs || verify)
        for (const name of Object.keys(paths)) geo.handle(name);
      return geo;
    } catch (e) {
      await geo.close();
      throw e;
    }
  }
  handle(family) {
    if (this.#closed) throw new ClosedGeocoderError();
    if (!this.#paths[family]) throw new DataNotInstalledError(family);
    if (!this.#handles.has(family)) {
      const filename = this.#paths[family];
      try {
        if (!fs.existsSync(filename))
          throw new PackNotFoundError(`Pack not found: ${filename}`);
        const pack =
          family !== "core" && this.#paths.core
            ? this.#module.Geocoder.openWithCore(
                filename,
                this.#verify,
                this.handle("core"),
              )
            : this.#module.Geocoder.open(filename, this.#verify);
        this.#handles.set(family, pack);
      } catch (e) {
        throw atPack(e, filename, family);
      }
    }
    return this.#handles.get(family);
  }
  async reverse(point) {
    if (!point || typeof point !== "object" || Array.isArray(point))
      throw new TypeError("Use a named {lat, lon} coordinate object");
    const { lat, lon, evidence = false } = point;
    if (typeof evidence !== "boolean")
      throw new TypeError("evidence must be boolean");
    try {
      return freeze(
        JSON.parse(
          this.handle("core").reverse(
            typeof lat === "number" ? lat : NaN,
            typeof lon === "number" ? lon : NaN,
            evidence,
          ),
        ),
      );
    } catch (e) {
      throw convert(e);
    }
  }
  async reversePoint(point, options = {}) {
    if (this.#closed) throw new ClosedGeocoderError();
    const request = coordinateRequest(point);
    const evidence = coordinateEvidence(options);
    try {
      return freeze(
        JSON.parse(this.handle("core").reversePoint(request, evidence)),
      );
    } catch (e) {
      throw convert(e);
    }
  }
  async *reversePoints(points, options = {}) {
    if (this.#closed) throw new ClosedGeocoderError();
    coordinateEvidence(options);
    for await (const point of points) {
      if (this.#closed) throw new ClosedGeocoderError();
      yield this.reversePoint(point, options);
      if (this.#closed) throw new ClosedGeocoderError();
    }
  }
  #query(verb, text, options = {}) {
    if (!options || typeof options !== "object" || Array.isArray(options))
      throw new TypeError("Query options must be an object");
    const allowed = {
      h3: [],
      postal: ["country"],
      airport: ["country", "scheme"],
      locode: ["country"],
      phone: ["country"],
      ip: [],
      plate: ["country", "series"],
      geocode: ["country", "subdivision", "limit", "prefer", "scope"],
    }[verb];
    for (const [key, value] of Object.entries(options)) {
      if (key !== "evidence" && !allowed.includes(key))
        throw new TypeError(`Unknown ${verb} option: ${key}`);
      if (
        value !== undefined &&
        value !== null &&
        key !== "limit" &&
        typeof value !== (key === "evidence" ? "boolean" : "string")
      )
        throw new TypeError(`Invalid ${key} option type`);
    }
    const request = {
      verb,
      text: typeof text === "string" ? text : "",
      ...options,
    };
    if (
      verb === "geocode" &&
      (!Number.isInteger(request.limit ?? 5) || (request.limit ?? 5) < 0)
    )
      request.limit = 0;
    try {
      return freeze(
        JSON.parse(this.handle(families[verb]).query(JSON.stringify(request))),
      );
    } catch (e) {
      throw convert(e);
    }
  }
  async fromH3(cell, options) {
    return this.#query("h3", cell, options);
  }
  async postal(code, options) {
    return this.#query("postal", code, options);
  }
  async airport(code, options) {
    return this.#query("airport", code, options);
  }
  async locode(code, options) {
    return this.#query("locode", code, options);
  }
  async phone(number, options) {
    return this.#query("phone", number, options);
  }
  async ip(address, options) {
    return this.#query("ip", address, options);
  }
  async plate(text, options) {
    return this.#query("plate", text, options);
  }
  /** Finds towns and cities by name. Street addresses are not supported. */
  async geocode(text, options) {
    return this.#query("geocode", text, options);
  }
  async *reverseMany(points, options = {}) {
    if (this.#closed) throw new ClosedGeocoderError();
    for await (const point of points) {
      if (
        !point ||
        Array.isArray(point) ||
        !("lat" in point) ||
        !("lon" in point)
      )
        throw new TypeError("Each point must have named lat and lon fields");
      yield this.reverse({ lat: point.lat, lon: point.lon, ...options });
    }
  }
  async close() {
    if (this.#closed) return;
    this.#closed = true;
    for (const pack of this.#handles.values()) pack.free();
    this.#handles.clear();
  }
  [Symbol.asyncDispose]() {
    return this.close();
  }
}
