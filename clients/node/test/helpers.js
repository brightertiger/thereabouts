import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { sha256 } from "../runtime/store.js";
export const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
export const FIXTURES = path.join(ROOT, "tests/fixtures");
export const BIN = fileURLToPath(
  new URL("../bin/thereabouts.js", import.meta.url),
);
export function json(filename) {
  return JSON.parse(fs.readFileSync(filename, "utf8"));
}
export function temporary(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thereabouts-node-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}
export function selection(pack) {
  const filename = path.join(FIXTURES, pack),
    manifest = json(path.join(filename, "manifest.json"));
  const packs = { [manifest.family]: filename };
  if (manifest.family !== "core")
    packs.core = path.join(
      FIXTURES,
      `packs/core-${manifest.data_version === "synthetic" ? "synthetic" : "sample"}`,
    );
  return packs;
}
function linkTree(source, target) {
  fs.mkdirSync(target, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name),
      to = path.join(target, entry.name);
    if (entry.isDirectory()) linkTree(from, to);
    else fs.linkSync(from, to);
  }
}
export function fixtureStore(root, packs) {
  let pin;
  for (const [family, source] of Object.entries(packs)) {
    const info = json(path.join(source, "manifest.json"));
    pin ??= { data_version: info.data_version, packs: {} };
    if (pin.data_version !== info.data_version)
      throw new Error("Fixture versions differ");
    const relative = `packs/${family}/${info.data_version}`,
      destination = path.join(root, relative);
    linkTree(source, destination);
    pin.packs[family] = {
      path: relative,
      manifest_sha256: sha256(path.join(destination, "manifest.json")),
    };
  }
  fs.writeFileSync(path.join(root, "active.json"), JSON.stringify(pin));
}
export function console(root, args, input = "", env = {}) {
  return spawnSync(
    process.execPath,
    [
      "--import",
      fileURLToPath(new URL("./offline.js", import.meta.url)),
      BIN,
      "--data-dir",
      root,
      ...args,
    ],
    {
      input,
      encoding: "utf8",
      timeout: 30_000,
      env: { ...process.env, ...env },
    },
  );
}
export function lookup(geo, request, evidence = false) {
  const { kind, values, ...options } = request;
  if (kind === "coordinates")
    return geo.reverse({ lat: values[0], lon: values[1], evidence });
  return geo[kind === "h3" ? "fromH3" : kind](values[0], {
    ...(kind === "ip" ? {} : options),
    evidence,
  });
}
export function argumentsFor(request) {
  if (request.kind === "coordinates")
    return [
      "reverse",
      "--lat",
      String(request.values[0]),
      "--lon",
      String(request.values[1]),
    ];
  return [
    request.kind,
    ...Object.entries(request)
      .filter(
        ([k, v]) =>
          !["kind", "values"].includes(k) &&
          v !== null &&
          request.kind !== "ip",
      )
      .flatMap(([k, v]) => ["--" + k, String(v)]),
    "--",
    String(request.values[0]),
  ];
}
export const USAGE = new Set([
  "postal-022",
  "airports-027",
  "core-names-sample-034",
  "core-names-sample-035",
  "core-names-sample-036",
  "core-names-sample-037",
]);

// Same 1e-10 absolute numeric tolerance as Rust's conformance runner:
// WASM and native transcendental functions differ by a few ULPs for H3 centres.
export function assertResult(assert, actual, expected, label) {
  if (typeof expected === "number" && !Number.isInteger(expected)) {
    assert.equal(typeof actual, "number", label);
    assert.ok(Math.abs(actual - expected) < 1e-10, label);
    return;
  }
  if (expected && typeof expected === "object") {
    assert.deepEqual(
      Object.keys(actual).sort(),
      Object.keys(expected).sort(),
      label,
    );
    for (const key of Object.keys(expected))
      assertResult(assert, actual[key], expected[key], label + "." + key);
  } else assert.deepEqual(actual, expected, label);
}
