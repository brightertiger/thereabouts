import { execFileSync } from "node:child_process";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { Geocoder, requireOne, AmbiguousResultError } from "../src/index.js";

export const fixtures = fileURLToPath(
  new URL("../../../tests/fixtures/", import.meta.url),
);
const bundle = JSON.parse(
  await readFile(`${fixtures}/conformance.json`, "utf8"),
);
assert.equal(bundle.schema, "thereabouts-conformance-1");
export async function resolve(reader, request) {
  const { kind, values, country, scheme } = request;
  if (kind === "coordinates") return reader.reverse(...values);
  if (kind === "h3") return reader.fromH3(values[0]);
  return reader[kind](values[0], { country, scheme });
}
for (const fixture of [...new Set(bundle.cases.map((c) => c.pack))]) {
  test(`Python conformance: ${fixture}`, async () => {
    const reader = await Geocoder.open({
      pack: `${fixtures}/${fixture}`,
      verify: true,
    });
    try {
      for (const item of bundle.cases.filter((c) => c.pack === fixture)) {
        if (item.error)
          await assert.rejects(resolve(reader, item.request), item.error);
        else {
          const result = await resolve(reader, item.request);
          assert.deepEqual(result, item.result, `case ${item.id}`);
          assert.deepEqual(reader.explain(result), {
            result,
            raw_evidence_installed: false,
          });
          if (result.status === "ambiguous")
            assert.throws(() => requireOne(result), AmbiguousResultError);
          else assert.equal(requireOne(result), result.selected);
        }
      }
    } finally {
      await reader.close();
    }
  });
}

test("legacy packaged specification matches its recorded historical contract", async () => {
  const packaged = await readFile(new URL("../FORMAT.md", import.meta.url));
  const source = execFileSync("git", ["show", "3ade5da:docs/SERVING_FORMAT.md"], {
    cwd: new URL("../../../", import.meta.url),
  });
  const standalone = source
    .toString()
    .replaceAll(
      "[CLIENT_STATUS.md](CLIENT_STATUS.md)",
      "CLIENT_STATUS.md in the repository docs directory",
    )
    .replaceAll(
      "[CODE_PACKS.md](CODE_PACKS.md)",
      "CODE_PACKS.md in the repository docs directory",
    );
  assert.equal(packaged.toString(), standalone);
});
