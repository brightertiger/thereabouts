import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { Geocoder } from "../runtime/index.js";
import { run } from "../runtime/cli.js";
import {
  json,
  FIXTURES,
  temporary,
  selection,
  fixtureStore,
  lookup,
  argumentsFor,
  console,
  USAGE,
  assertResult,
} from "./helpers.js";
const bundles = fs
  .readdirSync(FIXTURES)
  .filter((name) => name.endsWith("-vectors.json"))
  .sort();
for (const name of bundles) {
  const bundle = json(path.join(FIXTURES, name));
  test(`library vectors: ${name} (${bundle.cases.length})`, async (t) => {
    const geo = await Geocoder.open({ packs: selection(bundle.pack) });
    t.after(() => geo.close());
    for (const c of bundle.cases)
      assertResult(assert, await lookup(geo, c.request), c.result, c.id);
  });
  test(`bin vectors: ${name} (${bundle.cases.length})`, async (t) => {
    const root = temporary(t);
    fixtureStore(root, selection(bundle.pack));
    for (const c of bundle.cases) {
      const args = argumentsFor(c.request);
      if (
        c.request.kind !== "coordinates" &&
        typeof c.request.values[0] !== "string"
      )
        continue;
      // Synthetic reverse vectors retain typed invalid coordinate cases. OS argv
      // can only preserve strings; these remain asserted through the library.
      if (
        c.request.kind === "coordinates" &&
        c.request.values.some((v) => typeof v !== "number")
      )
        continue;
      let output;
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
        output = { status, stdout, stderr };
      } else output = console(root, args);
      if (
        USAGE.has(c.id) ||
        (c.request.kind === "postal" && !c.request.country) ||
        (c.request.limit !== undefined &&
          (c.request.limit < 1 || c.request.limit > 100))
      ) {
        assert.equal(c.result.status, "invalid_input");
        assert.equal(output.status, 2, c.id);
        assert.equal(output.stdout, "");
        continue;
      }
      const code = ["invalid_input", "unsupported_granularity"].includes(
        c.result.status,
      )
        ? 2
        : 0;
      assert.equal(output.status, code, `${c.id}: ${output.stderr}`);
      assertResult(assert, JSON.parse(output.stdout), c.result, c.id);
    }
  });
}
