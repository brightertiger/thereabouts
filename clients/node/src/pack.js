import { join } from "node:path";
import { Cache } from "./cache.js";
import { File } from "./files.js";
import { readManifest } from "./manifest.js";
import { container } from "./container.js";
import { catalogueHeader, verifyCatalogue } from "./catalogue.js";
import { exactHeader, exactLookup, verifyExact } from "./exact.js";
import { loadBlock, lookup, spatialDirectory } from "./spatial.js";
import { address, query } from "./address.js";
import {
  codeMatches,
  codeResult,
  dataIdentity,
  reverseResult,
} from "./results.js";
import { compound, countryCode, normalize } from "./keys.js";
import { check, CorruptPackError, InvalidInputError } from "./errors.js";
import { freeze } from "./json.js";

export class Pack {
  constructor(root, manifest, cacheBytes) {
    this.root = root;
    this.manifest = freeze(manifest);
    this.data = dataIdentity(manifest);
    // The populated sample retains 4.8 MB of buffers and more than 16 MB of
    // decoded catalogue entries; reserve three quarters for decoded objects.
    this.raw = new Cache(Math.floor(cacheBytes / 4));
    this.decoded = new Cache(cacheBytes - this.raw.budget);
    this.blocks = new Map();
    this.catalogues = [];
    this.exacts = [];
  }
  static async open(root, cacheBytes, full) {
    const pack = new Pack(root, await readManifest(root, full), cacheBytes);
    for (const record of pack.manifest.files) {
      if (record.kind === "notice") continue;
      const file = new File(join(root, record.path), record.size, pack.raw);
      const sections = await container(file, record.kind);
      const shard = { file, sections, record };
      if (record.kind === "cells") await spatialDirectory(shard, pack.blocks);
      else if (record.kind === "catalogue") {
        await catalogueHeader(shard);
        pack.catalogues.push(shard);
      } else {
        await exactHeader(shard);
        pack.exacts.push(shard);
      }
    }
    if (pack.manifest.coverage === "world")
      check(pack.blocks.size === 41162, "Incomplete world coverage");
    if (full) await pack.verifyStructure();
    return pack;
  }
  async verifyStructure() {
    await verifyCatalogue(this);
    for (const entry of this.blocks.values())
      await loadBlock(entry, this.raw, this.manifest.place_count);
    try {
      await verifyExact(this);
    } catch (error) {
      if (error instanceof InvalidInputError)
        throw new CorruptPackError("Invalid stored code key", { cause: error });
      throw error;
    }
  }
  async reverse(input) {
    const { block, suffix } = address(input.cell);
    const entry = this.blocks.get(block);
    const bytes = entry
      ? await loadBlock(entry, this.raw, this.manifest.place_count)
      : null;
    const hit = entry ? lookup(entry, bytes, suffix) : null;
    return reverseResult(this, input, block, Boolean(entry), hit);
  }
  async code(value, country, scheme) {
    country = country == null ? null : countryCode(country);
    const normalized = normalize(
      value,
      this.manifest.key_normalization,
      country,
    );
    const wanted = compound(this.manifest.family, normalized, country, scheme);
    let matches = this.decoded.get(wanted);
    if (!matches) {
      matches = await codeMatches(this, await exactLookup(this, wanted));
      this.decoded.put(wanted, matches);
    }
    return codeResult(
      this,
      query(this.manifest.family === "postal" ? "postal" : "airport", {
        value: normalized,
        country,
        scheme,
      }),
      matches,
    );
  }
  close() {
    this.raw.clear();
    this.decoded.clear();
  }
  cacheInfo() {
    return { raw: this.raw.info(), decoded: this.decoded.info() };
  }
}
