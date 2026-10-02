import { setTimeout } from "node:timers/promises";
import { readFile, writeFile } from "node:fs/promises";
import { performance, monitorEventLoopDelay } from "node:perf_hooks";
import { cpus, release, totalmem } from "node:os";
import { Geocoder } from "./src/index.js";

const [pack, queries, output] = process.argv.slice(2);
if (!pack || !queries || !output)
  throw new Error("Usage: node benchmark.mjs PACK QUERIES.json OUTPUT.json");
const points = JSON.parse(await readFile(queries, "utf8"));
let start = performance.now();
const reader = await Geocoder.open({ pack });
const openMs = performance.now() - start;
const delay = monitorEventLoopDelay({ resolution: 5 });
delay.enable();
await setTimeout(10);
start = performance.now();
await reader.reverse(...points[0]);
const firstUs = (performance.now() - start) * 1000;
start = performance.now();
for await (const row of reader.reverseMany(points)) void row;
const coldSeconds = (performance.now() - start) / 1000;
const coldDelay = {
  p99_ms: delay.percentile(99) / 1e6,
  max_ms: delay.max / 1e6,
};
delay.reset();
const timings = [];
for (let i = 0; i < 10000; i++) {
  start = performance.now();
  await reader.reverse(...points[i % points.length]);
  timings.push((performance.now() - start) * 1000);
}
timings.sort((a, b) => a - b);
await setTimeout(10);
delay.reset();
const batch = [];
for (let i = 0; i < 5; i++) {
  start = performance.now();
  for await (const row of reader.reverseMany(points)) void row;
  batch.push((points.length * 1000) / (performance.now() - start));
}
delay.disable();
const info = reader.info();
const report = {
  machine: {
    cpu: cpus()[0].model,
    memory_bytes: totalmem(),
    os: release(),
    arch: process.arch,
    node: process.version,
    h3_js: "4.5.0",
  },
  sample: {
    query_count: points.length,
    manifest_sha256: info.packs.reverse.manifest_sha256,
    places: info.packs.reverse.place_count,
    pack_bytes:
      info.packs.reverse.files.reduce(
        (total, record) => total + record.size,
        0,
      ) + (await readFile(`${pack}/manifest.json`)).length,
  },
  open_ms: openMs,
  first_query_us: firstUs,
  first_pass_results_per_s: points.length / coldSeconds,
  scalar_warm_median_us: timings[5000],
  scalar_warm_p99_us: timings[9900],
  batch_object_results_per_s: batch,
  first_pass_event_loop: coldDelay,
  warm_event_loop: {
    p99_ms: delay.percentile(99) / 1e6,
    max_ms: delay.max / 1e6,
  },
  memory: process.memoryUsage(),
  peak_rss_bytes: process.resourceUsage().maxRSS * 1024,
  cache: info.cache,
  notes: [
    "Synthetic assignments; not geographic accuracy evidence.",
    "First pass is an empty reader cache, not a flushed OS disk cache.",
    "Warm event-loop measurement covers object batches, excluding scalar timing.",
  ],
};
await reader.close();
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
console.log(
  JSON.stringify({
    open_ms: openMs,
    first_query_us: firstUs,
    median_us: report.scalar_warm_median_us,
    batch: batch,
    peak_rss_bytes: report.peak_rss_bytes,
    cache: report.cache,
  }),
);
