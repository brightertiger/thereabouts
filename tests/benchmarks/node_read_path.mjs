// Reproducible Node/WASM measurements; no network or real dataset is required.
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn } from "node:child_process";
import { performance } from "node:perf_hooks";
import assert from "node:assert/strict";
import { assertLegacy } from "../../clients/node/test/legacy.js";
import { USAGE, argumentsFor } from "../../clients/node/test/helpers.js";
import { Geocoder } from "../../clients/node/runtime/index.js";
import { FIXTURES, ROOT, json, selection, lookup, fixtureStore } from "../../clients/node/test/helpers.js";
import { sha256 } from "../../clients/node/runtime/store.js";
// All subprocess caches, logs and temporary spools stay in this checkout.
const scratch = path.join(ROOT, ".tmp");
fs.mkdirSync(scratch, { recursive: true });
process.env.TMPDIR = scratch;
process.env.npm_config_cache = path.join(ROOT, ".cache/npm");
process.env.npm_config_logs_dir = path.join(ROOT, ".cache/npm/_logs");
const ITERATIONS = 10000, LAUNCHES = 30;
function percentile(values, fraction) { return [...values].sort((a, b) => a - b)[Math.min(values.length - 1, Math.ceil(values.length * fraction) - 1)]; }
const bundles = { reverse: "core-sample", postal: "postal", airport: "airports", locode: "locode", phone: "phone", ip: "ip", plate: "plates", geocode: "geocode" };
const report = { node: process.version, platform: process.platform, arch: process.arch, cpu: os.cpus()[0].model, memory_bytes: os.totalmem(), iterations: ITERATIONS, file_cache: "warm; no filesystem cache flush", verbs: {} };
for (const [verb, name] of Object.entries(bundles)) {
  const bundle = json(path.join(FIXTURES, name + "-vectors.json"));
  const requests = bundle.cases.filter((c) => c.result.status === "matched" && (verb !== "reverse" || c.request.kind === "coordinates")).map((c) => c.request);
  const started = performance.now(), rss = process.memoryUsage().rss;
  const geo = await Geocoder.open({ packs: selection(bundle.pack) });
  const opened = performance.now() - started, rssDelta = process.memoryUsage().rss - rss;
  try {
    for (let i = 0; i < 1000; i++) await lookup(geo, requests[i % requests.length]);
    const hot = [], varied = [];
    for (let i = 0; i < ITERATIONS; i++) {
      let start = performance.now(); await lookup(geo, requests[0]); hot.push((performance.now() - start) * 1000);
      start = performance.now(); await lookup(geo, requests[i % requests.length]); varied.push((performance.now() - start) * 1000);
    }
    const batches = [];
    for (let repeat = 0; repeat < 5; repeat++) {
      const start = performance.now(); let count = 0;
      if (verb === "reverse") {
        const points = Array.from({ length: ITERATIONS }, (_, i) => ({ lat: requests[i % requests.length].values[0], lon: requests[i % requests.length].values[1] }));
        for await (const value of geo.reverseMany(points)) { if (value.status !== "matched") throw new Error("Unexpected miss"); count++; }
      } else for (let i = 0; i < ITERATIONS; i++) { await lookup(geo, requests[i % requests.length]); count++; }
      batches.push(count / ((performance.now() - start) / 1000));
    }
    report.verbs[verb] = { pack: bundle.pack, request_count: requests.length, open_ms: opened, open_rss_delta_bytes: rssDelta,
      scalar_median_us: percentile(hot, .5), scalar_p99_us: percentile(hot, .99),
      varied_median_us: percentile(varied, .5), varied_p99_us: percentile(varied, .99),
      batch_points_per_second: percentile(batches, .5), batch_repeats: batches,
      batch_api: verb === "reverse" ? "reverseMany async iterable" : "ordered scalar loop; no vectorized forward API",
    };
  } finally { geo.close(); }
}

const vectorFiles = fs.readdirSync(FIXTURES).filter((name) => name.endsWith("-vectors.json"));
const boundaries = { total: 0, os_argv: 0, nul_runner: 0, typed_library: 0, grammar_usage: 0 };
for (const filename of vectorFiles) for (const c of json(path.join(FIXTURES, filename)).cases) {
  boundaries.total++;
  const r = c.request;
  if (r.kind === "coordinates" ? r.values.some((v) => typeof v !== "number") : typeof r.values[0] !== "string") { boundaries.typed_library++; continue; }
  if (argumentsFor(r).some((v) => v.includes("\0"))) boundaries.nul_runner++; else boundaries.os_argv++;
  if (USAGE.has(c.id) || r.kind === "postal" && !r.country || r.limit !== undefined && (r.limit < 1 || r.limit > 100)) boundaries.grammar_usage++;
}
const legacyCases = json(path.join(FIXTURES, "conformance.json")).cases;
const legacy = await Geocoder.open({ packs: Object.fromEntries(["core", "postal", "airports"].map((f) => [f, path.join(FIXTURES, "packs/" + f + "-synthetic")])) });
const mappings = {};
let legacyTyped = 0, legacyUsage = 0;
try {
  for (const c of legacyCases) {
    const r = c.request, status = assertLegacy(await lookup(legacy, r, true), c, legacyCases);
    mappings[status] = (mappings[status] ?? 0) + 1;
    if (r.kind === "coordinates" ? r.values.some((v) => typeof v !== "number") : typeof r.values[0] !== "string") legacyTyped++;
    else if (r.kind === "postal" && !r.country) legacyUsage++;
  }
} finally { await legacy.close(); }
assert.equal(boundaries.total, 478); assert.equal(legacyCases.length, 54);
report.conformance = { current: boundaries, legacy: { total: legacyCases.length, os_argv_results: legacyCases.length - legacyTyped - legacyUsage, grammar_usage: legacyUsage, typed_library: legacyTyped, mappings }, numeric_absolute_tolerance: 1e-10 };
const wasm = path.join(ROOT, "clients/node/pkg/thereabouts_bg.wasm");
report.wasm = { bytes: fs.statSync(wasm).size, sha256: sha256(wasm), committed: false, build: "npm run build (cargo --locked release wasm32 + wasm-bindgen 0.2.129)" };
const temp = fs.mkdtempSync(path.join(ROOT, ".tmp/node-startup-"));
async function sample(command, args) {
  const start = performance.now();
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: path.join(ROOT, "clients/node"), env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    let output = "", error = "", first;
    child.stdout.on("data", (data) => { output += data; if (first === undefined && output.includes("\n")) first = performance.now() - start; });
    child.stderr.on("data", (data) => error += data); child.on("error", reject);
    child.on("close", (code) => { if (code !== 0 || JSON.parse(output).status !== "matched") reject(new Error(error || "Invalid benchmark output")); else resolve({ first_ms: first, total_ms: performance.now() - start }); });
  });
}
try {
  fixtureStore(temp, selection("packs/core-sample"));
  const args = ["--data-dir", temp, "reverse", "--lat", "48.8566", "--lon", "2.3522"];
  report.startup = {};
  for (const [name, command, prefix] of [["bin", process.execPath, [path.join(ROOT, "clients/node/bin/thereabouts.js")]], ["npx", process.platform === "win32" ? "npx.cmd" : "npx", ["--offline", "--no", "--", "thereabouts"]]]) {
    const initial = await sample(command, [...prefix, ...args]);
    for (let i = 0; i < 2; i++) await sample(command, [...prefix, ...args]);
    const values = []; for (let i = 0; i < LAUNCHES; i++) values.push(await sample(command, [...prefix, ...args]));
    report.startup[name] = { launches: LAUNCHES, warmups: 3, first_launch_ms: initial.first_ms, first_result_median_ms: percentile(values.map((v) => v.first_ms), .5), first_result_p99_ms: percentile(values.map((v) => v.first_ms), .99), samples: values };
  }
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
const output = path.join(ROOT, "tests/benchmarks/measurements/CLIENT_CORE_MEASUREMENTS.json"), existing = json(output);
existing.node_wasm = report; fs.writeFileSync(output, JSON.stringify(existing, null, 2) + "\n");
fs.writeFileSync(path.join(ROOT, "tests/benchmarks/measurements/CLIENT_NODE_MEASUREMENTS.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));
