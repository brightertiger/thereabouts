// Answer a probe job with the Node client: node node_queries.mjs JOB OUTPUT.
// The job and output shapes match pipeline/release/probe.py, so the end-to-end
// driver judges and compares both clients' answers the same way.
import fs from "node:fs";
import { performance } from "node:perf_hooks";
import { Geocoder } from "../../clients/node/runtime/index.js";

function call(geo, request, evidence) {
  const { kind, values, ...rest } = request;
  const options = Object.fromEntries(
    Object.entries(rest).filter(([, value]) => value !== null),
  );
  if (kind === "coordinates")
    return geo.reverse({ lat: values[0], lon: values[1], evidence });
  if (kind === "h3") return geo.fromH3(values[0], { evidence });
  if (kind === "ip") return geo.ip(values[0], { evidence });
  return geo[kind](values[0], { ...options, evidence });
}

const [jobPath, outputPath] = process.argv.slice(2);
const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
let started = performance.now();
const geo = await Geocoder.open(
  job.packs ? { packs: job.packs } : { dataDir: job.data_dir },
);
const openSeconds = (performance.now() - started) / 1000;
const lines = [];
const latencies = [];
for (const query of job.queries) {
  started = performance.now();
  try {
    const result = await call(geo, query.request, query.evidence);
    lines.push(JSON.stringify({ id: query.id, result }));
  } catch (error) {
    lines.push(
      JSON.stringify({ id: query.id, error: `${error.name}: ${error.message}` }),
    );
  }
  latencies.push(performance.now() - started);
}
await geo.close();
latencies.sort((a, b) => a - b);
const at = (share) =>
  latencies.length
    ? latencies[Math.min(latencies.length - 1, Math.floor(share * latencies.length))]
    : null;
lines.push(
  JSON.stringify({
    summary: {
      open_seconds: openSeconds,
      queries: latencies.length,
      p50_ms: at(0.5),
      p99_ms: at(0.99),
    },
  }),
);
fs.writeFileSync(outputPath, lines.join("\n") + "\n");
