import { setImmediate } from "node:timers/promises";
import { Pack } from "./pack.js";
import { coordinates, h3Input, query } from "./address.js";
import {
  ClosedReaderError,
  IncompatibleDataError,
  InvalidInputError,
} from "./errors.js";
import { freeze } from "./json.js";
import { installedPack } from "./store.js";

export class Geocoder {
  #packs;
  #closed = false;
  #active = new Set();
  #closing;
  constructor(token, packs) {
    if (token !== Geocoder) throw new TypeError("Use await Geocoder.open()");
    this.#packs = packs;
  }
  static async open({
    pack,
    packs,
    dataDir,
    verify = false,
    cacheBytes = 32 * 1024 * 1024,
  } = {}) {
    if (!Number.isSafeInteger(cacheBytes) || cacheBytes < 0)
      throw new InvalidInputError("cacheBytes must be a nonnegative integer");
    if (pack !== undefined && packs !== undefined)
      throw new InvalidInputError("Choose pack or packs");
    if (typeof verify !== "boolean")
      throw new InvalidInputError("verify must be boolean");
    let paths;
    if (pack !== undefined) paths = [[null, pack]];
    else if (packs !== undefined && !Array.isArray(packs))
      paths = Object.entries(packs);
    else {
      paths = [];
      for (const family of packs ?? ["reverse"])
        paths.push([family, await installedPack(dataDir, family)]);
    }
    if (!paths.length) throw new InvalidInputError("Select at least one pack");
    const opened = new Map();
    let first = null;
    for (const [requested, path] of paths) {
      const reader = await Pack.open(
        path,
        Math.floor(cacheBytes / paths.length),
        verify,
      );
      const manifest = reader.manifest;
      if (requested !== null && requested !== manifest.family)
        throw new IncompatibleDataError("Pack family mismatch");
      if (opened.has(manifest.family))
        throw new InvalidInputError("Duplicate pack family");
      if (first) {
        for (const field of [
          "catalogue_epoch",
          "golden_sha256",
          "policy_sha256",
          "h3_version",
        ]) {
          if (first[field] !== manifest[field])
            throw new IncompatibleDataError(`Incompatible ${field}`);
        }
      }
      first = manifest;
      opened.set(manifest.family, reader);
    }
    return new Geocoder(Geocoder, opened);
  }
  #check() {
    if (this.#closed) throw new ClosedReaderError("Reader is closed");
  }
  #pack(family) {
    this.#check();
    const pack = this.#packs.get(family);
    if (!pack) throw new IncompatibleDataError(`No ${family} pack selected`);
    return pack;
  }
  async #run(family, work) {
    const pack = this.#pack(family);
    const promise = work(pack);
    this.#active.add(promise);
    try {
      return await promise;
    } finally {
      this.#active.delete(promise);
    }
  }
  async reverse(latitude, longitude) {
    return this.#run("reverse", (pack) =>
      pack.reverse(coordinates(latitude, longitude)),
    );
  }
  async fromH3(cell) {
    return this.#run("reverse", (pack) => pack.reverse(h3Input(cell)));
  }
  async postal(value, { country = null } = {}) {
    return this.#run("postal", (pack) => pack.code(value, country, null));
  }
  async airport(value, { country = null, scheme = null } = {}) {
    return this.#run("airports", (pack) => pack.code(value, country, scheme));
  }
  async *#batch(values, kind, { errors = "raise", chunkSize = 256 } = {}) {
    if (
      !["raise", "collect"].includes(errors) ||
      !Number.isSafeInteger(chunkSize) ||
      chunkSize < 1
    )
      throw new InvalidInputError("Invalid batch options");
    this.#check();
    let index = 0;
    for await (const value of values) {
      this.#check();
      let result;
      try {
        if (kind === "coordinates") {
          if (!Array.isArray(value) || value.length !== 2)
            throw new InvalidInputError("Expected a latitude/longitude pair");
          result = await this.reverse(value[0], value[1]);
        } else result = await this.fromH3(value);
      } catch (error) {
        if (!(error instanceof InvalidInputError) || errors === "raise")
          throw error;
        result = freeze({
          status: "invalid_input",
          selected: null,
          candidates: [],
          query: query(kind),
          reference: null,
          data: this.#pack("reverse").data,
          warnings: [],
          error: { code: "invalid_input", message: error.message },
        });
      }
      this.#check();
      yield result;
      if (++index % chunkSize === 0) await setImmediate();
    }
    this.#check();
  }
  reverseMany(points, options) {
    return this.#batch(points, "coordinates", options);
  }
  fromH3Many(cells, options) {
    return this.#batch(cells, "h3", options);
  }
  info() {
    this.#check();
    return {
      backend: "javascript",
      packs: Object.fromEntries(
        [...this.#packs].map(([name, pack]) => [
          name,
          structuredClone(pack.manifest),
        ]),
      ),
      cache: Object.fromEntries(
        [...this.#packs].map(([name, pack]) => [name, pack.cacheInfo()]),
      ),
    };
  }
  explain(result) {
    this.#check();
    return { result: structuredClone(result), raw_evidence_installed: false };
  }
  async close() {
    if (!this.#closing) {
      this.#closed = true;
      this.#closing = Promise.allSettled([...this.#active]).then(() => {
        for (const pack of this.#packs.values()) pack.close();
        this.#packs.clear();
      });
    }
    await this.#closing;
  }
}
