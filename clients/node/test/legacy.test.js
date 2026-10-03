import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { Geocoder } from "../runtime/index.js";
import { run } from "../runtime/cli.js";
import {
  FIXTURES,
  temporary,
  fixtureStore,
  json,
  lookup,
  argumentsFor,
  console,
} from "./helpers.js";
import { assertLegacy } from "./legacy.js";
const cases = json(path.join(FIXTURES, "conformance.json")).cases;
const packs = Object.fromEntries(
  ["core", "postal", "airports"].map((f) => [
    f,
    path.join(FIXTURES, `packs/${f}-synthetic`),
  ]),
);
test("54 unchanged legacy expectations through library (explicit status mapping)", async () => {
  const geo = await Geocoder.open({ packs });
  const counts = {};
  try {
    for (const c of cases) {
      const status = assertLegacy(await lookup(geo, c.request, true), c, cases);
      counts[status] = (counts[status] ?? 0) + 1;
    }
  } finally {
    geo.close();
  }
  assert.deepEqual(counts, {
    matched: 30,
    unassigned: 1,
    ineligible: 4,
    outside_coverage: 2,
    invalid_input: 11,
    coarse_cell_intended_change: 1,
    ambiguous: 3,
    not_found: 2,
  });
});
test("legacy expectations through bin, preserving OS argument boundaries", async (t) => {
  const root = temporary(t);
  fixtureStore(root, packs);
  let resultCount = 0,
    usageCount = 0,
    typedCount = 0;
  for (const c of cases) {
    const r = c.request;
    if (
      r.kind === "coordinates" &&
      r.values.some((v) => typeof v !== "number")
    ) {
      typedCount++;
      continue;
    }
    if (r.kind !== "coordinates" && typeof r.values[0] !== "string") {
      typedCount++;
      continue;
    }
    const args = ["--evidence", ...argumentsFor(r)];
    let result;
    if (args.some((v) => v.includes("\0"))) {
      let stdout = "",
        stderr = "";
      const status = await run(["--data-dir", root, ...args], {
        stdout: (s) => (stdout += s),
        stderr: (s) => (stderr += s),
        env: process.env,
        stdinTTY: false,
        stdoutTTY: false,
      });
      result = { status, stdout, stderr };
    } else result = console(root, args);
    if (
      (r.kind === "postal" && !r.country) ||
      (r.scheme &&
        !["iata", "icao", "gps", "ident", "local"].includes(
          r.scheme.toLowerCase(),
        ))
    ) {
      assert.ok(c.error);
      assert.equal(result.status, 2);
      assert.equal(result.stdout, "");
      usageCount++;
      continue;
    }
    assert.ok(result.stdout, `${c.id}: ${result.stderr}`);
    assertLegacy(JSON.parse(result.stdout), c, cases);
    resultCount++;
  }
  assert.equal(resultCount + usageCount + typedCount, 54);
  t.diagnostic(JSON.stringify({ resultCount, usageCount, typedCount }));
});
