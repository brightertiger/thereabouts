import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  Geocoder,
  ClosedGeocoderError,
  DataNotInstalledError,
  PackNotFoundError,
  CorruptPackError,
} from "../runtime/index.js";
import { handleCount } from "../runtime/host.js";
import { directory } from "../runtime/store.js";
import { FIXTURES, temporary, selection, fixtureStore } from "./helpers.js";
test("frozen detached results, async iterator ordering and explicit lifetime", async () => {
  const before = handleCount(),
    geo = await Geocoder.open({ packs: selection("packs/core-sample") });
  const points = [
    { lat: 48.8566, lon: 2.3522 },
    { lat: 51, lon: 4 },
  ];
  const expected = await Promise.all(points.map((p) => geo.reverse(p)));
  const results = [];
  async function* input() {
    yield* points;
  }
  for await (const value of geo.reverseMany(input(), { evidence: true }))
    results.push(value);
  assert.deepEqual(
    results.map((r) => r.city),
    expected.map((r) => r.city),
  );
  assert.throws(() => (results[0].city.name = "changed"), TypeError);
  await assert.rejects(async () => {
    for await (const r of geo.reverseMany([[1, 2]])) void r;
  }, TypeError);
  geo.close();
  geo.close();
  assert.equal(handleCount(), before);
  await assert.rejects(geo.reverse(points[0]), ClosedGeocoderError);
  assert.equal(results[0].city.name, "Paris");
});
test("standalone forward pack and core catalogue enrichment are explicit", async () => {
  const standalone = await Geocoder.open({
    pack: path.join(FIXTURES, "packs/postal-sample"),
  });
  const joined = await Geocoder.open({
    packs: selection("packs/postal-sample"),
  });
  try {
    const bare = await standalone.postal("9401 AA", { country: "NL" }),
      full = await joined.postal("9401 AA", { country: "NL" });
    assert.equal(bare.city, null);
    assert.equal(bare.timezone, null);
    assert.equal(full.timezone, "Europe/Amsterdam");
    assert.equal(full.city.name, "Assen");
    await assert.rejects(standalone.ip("8.8.8.8"), DataNotInstalledError);
  } finally {
    standalone.close();
    joined.close();
  }
});
test("host handles survive pathname replacement and reject symlink artifacts", async (t) => {
  const root = temporary(t),
    pack = path.join(root, "pack");
  fs.cpSync(path.join(FIXTURES, "packs/core-synthetic"), pack, {
    recursive: true,
  });
  const geo = await Geocoder.open({ pack });
  const moved = path.join(root, "moved");
  fs.renameSync(pack, moved);
  assert.equal((await geo.fromH3("8860140001fffff")).status, "matched");
  geo.close();
  const manifest = JSON.parse(
    fs.readFileSync(path.join(moved, "manifest.json")),
  );
  const relative = manifest.files.find((f) => f.kind === "cells").path;
  fs.renameSync(path.join(moved, relative), path.join(root, "shard"));
  fs.symlinkSync(path.join(root, "shard"), path.join(moved, relative));
  await assert.rejects(Geocoder.open({ pack: moved }), /Symlink/);
});
test("coded discovery/corruption failures do not leak handles", async (t) => {
  const root = temporary(t),
    before = handleCount();
  await assert.rejects(
    Geocoder.open({ dataDir: root }),
    (e) =>
      e instanceof DataNotInstalledError &&
      e.message === "thereabouts data install core",
  );
  await assert.rejects(
    Geocoder.open({ pack: path.join(root, "missing") }),
    PackNotFoundError,
  );
  fixtureStore(root, selection("packs/core-synthetic"));
  const pointer = path.join(root, "active.json"),
    pin = JSON.parse(fs.readFileSync(pointer));
  pin.packs.core.manifest_sha256 = "0".repeat(64);
  fs.writeFileSync(pointer, JSON.stringify(pin));
  await assert.rejects(Geocoder.open({ dataDir: root }), CorruptPackError);
  assert.equal(handleCount(), before);
});
test("platform store paths agree with documented Python/native policy", () => {
  assert.equal(
    directory(undefined, { HOME: "/home/test" }, "darwin"),
    "/home/test/Library/Application Support/Thereabouts",
  );
  assert.equal(
    directory(undefined, { HOME: "/home/test" }, "linux"),
    "/home/test/.local/share/thereabouts",
  );
  assert.equal(
    directory(undefined, { XDG_DATA_HOME: "/data" }, "linux"),
    "/data/thereabouts",
  );
  assert.equal(
    directory(undefined, { LOCALAPPDATA: "/local" }, "win32"),
    "/local/Thereabouts",
  );
  assert.equal(
    directory("~/custom", { HOME: "/home/test" }),
    "/home/test/custom",
  );
  assert.equal(
    directory("/explicit", { THEREABOUTS_DATA: "/env" }),
    "/explicit",
  );
});

test("full verification detects same-length corruption and selected family mismatch", async (t) => {
  const root = temporary(t),
    pack = path.join(root, "pack");
  fs.cpSync(path.join(FIXTURES, "packs/core-synthetic"), pack, {
    recursive: true,
  });
  const manifest = JSON.parse(
    fs.readFileSync(path.join(pack, "manifest.json")),
  );
  const shard = path.join(
    pack,
    manifest.files.find((f) => f.kind === "cells").path,
  );
  const bytes = fs.readFileSync(shard);
  bytes[bytes.length - 1] ^= 1;
  fs.writeFileSync(shard, bytes);
  await assert.rejects(
    Geocoder.open({ pack, verify: true }),
    (e) => e instanceof CorruptPackError && /checksum/.test(e.message),
  );
  await assert.rejects(
    Geocoder.open({
      packs: { postal: path.join(FIXTURES, "packs/core-synthetic") },
    }),
    /family or dataset/,
  );
});
