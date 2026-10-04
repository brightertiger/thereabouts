import test from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { temporary, fixtureStore, selection, console } from "./helpers.js";

function store(t) {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-sample"));
  return root;
}

test("coordinate syntax and no-data help use the shared grammar", (t) => {
  const root = temporary(t);
  for (const args of [
    ["--frame", "ecef", "--x", "1", "--y", "2"],
    ["--x", "1", "--y", "2", "--z", "3"],
    ["--lat", "0", "--lon", "0", "--hdop", "1"],
    ["--frame", "enu", "--x", "0", "--y", "0", "--z", "0"],
    ["--point", "{"],
    ["--point", "{}"],
    ["--point", '{"frame":"ecef"}', "--frame", "ecef"],
    ["-", "--point", '{"frame":"ecef"}'],
    ["--frame", "crs:EPSG:3857"],
    ["-", "--input-format", "nmea"],
    ["-", "--frame-col", "frame"],
  ]) {
    const result = console(root, ["reverse", ...args]);
    assert.equal(result.status, 2, args.join(" "));
    assert.equal(result.stdout, "");
    assert.doesNotMatch(result.stderr, /not installed/);
  }
  for (const args of [["reverse", "--help"], ["--fields"]]) {
    const result = console(root, args);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /--input-format|query.normalized.lat/);
  }
});

test("scalar frame requests call reversePoint with shared Rust assembly", (t) => {
  const root = store(t);
  const fixture = JSON.parse(
    readFileSync(
      new URL(
        "../../../tests/fixtures/coordinates/vectors.json",
        import.meta.url,
      ),
    ),
  );
  const vector = fixture.cases.find((c) => c.id === "msl_with_separation");
  const point = {
    ...vector.input,
    frame: "llh",
    uncertainty: { accuracy_m: 4, hdop: 1.2 },
  };
  const result = console(root, ["reverse", "--point", JSON.stringify(point)]);
  assert.equal(result.status, 0, result.stderr);
  const value = JSON.parse(result.stdout);
  assert.equal(
    value.query.normalized.height,
    vector.expected.normalized.height,
  );
  assert.equal(value.query.declared_frame, "llh");
  assert.deepEqual(value.query.uncertainty, {
    accuracy_m: 4,
    hdop: 1.2,
    vdop: null,
  });
  assert.equal(Object.keys(value).at(-1), "query");
  assert.ok(!("evidence" in value));
  const components = Object.entries(vector.input).flatMap(([key, value]) => [
    `--${key.replaceAll("_", "-")}`,
    String(value),
  ]);
  const scalar = console(root, [
    "reverse",
    "--frame",
    "llh",
    ...components,
    "--accuracy-m",
    "4",
    "--hdop",
    "1.2",
  ]);
  assert.equal(scalar.status, 0, scalar.stderr);
  assert.deepEqual(JSON.parse(scalar.stdout), value);
  const legacy = console(root, [
    "reverse",
    "--lat",
    "48.8566",
    "--lon",
    "2.3522",
  ]);
  assert.equal(legacy.status, 0, legacy.stderr);
  assert.ok(!("query" in JSON.parse(legacy.stdout)));
});

test("portable batches retain CSV fields and reserve query after bad first row", (t) => {
  const root = store(t);
  const result = console(
    root,
    [
      "reverse",
      "-",
      "--frame",
      "ecef",
      "--x-col",
      "X",
      "--y-col",
      "Y",
      "--z-col",
      "Z",
    ],
    'id,X,Z,Y,note\nbad,no,0,0,wrong\nok,6378137,0,0,"two\nlines"\n',
  );
  assert.equal(result.status, 5, result.stderr);
  const rows = result.stdout.trim().split("\n").map(JSON.parse);
  assert.deepEqual(Object.keys(rows[0]).slice(0, 5), [
    "id",
    "X",
    "Z",
    "Y",
    "note",
  ]);
  assert.equal(rows[0].thereabouts_status, "invalid_input");
  assert.equal(rows[1].note, "two\nlines");
  assert.equal(rows[1].thereabouts_query.input_frame, "ecef");
  const mixed = console(
    root,
    ["reverse", "-", "--input-format", "ndjson", "--csv"],
    'bad\n{"lat":0,"lon":0}\n{"frame":"ecef","x":6378137,"y":0,"z":0}\n',
  );
  assert.equal(mixed.status, 5, mixed.stderr);
  assert.match(mixed.stdout.split("\n")[0], /,thereabouts_query$/);
  assert.equal(mixed.stdout.trim().split("\n").length, 4);
  const pure = console(root, ["reverse", "-", "--csv"], '{"lat":0,"lon":0}\n');
  assert.equal(pure.status, 0, pure.stderr);
  assert.doesNotMatch(pure.stdout, /thereabouts_query/);
});

test("NMEA is explicit, checked per sentence and preserves its raw value", (t) => {
  const root = store(t);
  const sentence =
    "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47";
  const result = console(
    root,
    ["reverse", "-", "--frame", "nmea", "--input-format", "nmea"],
    `\n${sentence}\n\n$GPGGA,bad*00\n`,
  );
  assert.equal(result.status, 5, result.stderr);
  const rows = result.stdout.trim().split("\n").map(JSON.parse);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].value, sentence);
  assert.equal(rows[0].thereabouts_query.uncertainty.hdop, 0.9);
  assert.equal(rows[1].thereabouts_query.error.code, "invalid_checksum");
});

function assertMetadata(actual, expected, tolerances, key = "") {
  if (typeof expected === "number") {
    assert.equal(typeof actual, "number", key);
    let delta = Math.abs(actual - expected);
    if (key.endsWith(".lon")) delta = Math.min(delta, Math.abs(360 - delta));
    assert.ok(
      delta <= (tolerances[key] ?? 0),
      `${key}: ${actual} vs ${expected}`,
    );
  } else if (Array.isArray(expected)) {
    assert.equal(actual.length, expected.length, key);
    expected.forEach((v, i) =>
      assertMetadata(actual[i], v, tolerances, `${key}.*`),
    );
  } else if (expected && typeof expected === "object") {
    for (const [field, value] of Object.entries(expected))
      assertMetadata(
        actual[field],
        value,
        tolerances,
        key ? `${key}.${field}` : field,
      );
  } else assert.deepEqual(actual, expected, key);
}

test("shared coordinate fixtures drive real WASM CLI metadata", async (t) => {
  const root = store(t);
  const fixture = JSON.parse(
    readFileSync(
      new URL(
        "../../../tests/fixtures/coordinates/vectors.json",
        import.meta.url,
      ),
    ),
  );
  assert.equal(fixture.schema_version, 1);
  for (const vector of fixture.cases) {
    await t.test(vector.id, () => {
      const point = { frame: "geodetic", ...vector.input };
      const result = console(root, [
        "reverse",
        "--point",
        JSON.stringify(point),
      ]);
      assert.equal(
        result.status,
        vector.expected.error ? 2 : 0,
        `${vector.id}: ${result.stderr}`,
      );
      const value = JSON.parse(result.stdout);
      if (vector.expected.error) {
        assert.equal(value.status, "invalid_input", vector.id);
        assert.equal(value.query.error.code, vector.expected.error, vector.id);
      } else assertMetadata(value.query, vector.expected, vector.tolerance);
    });
  }
});

test("raw CSV frame columns never override the uniform declaration", (t) => {
  const result = console(
    store(t),
    ["reverse", "-", "--frame", "ecef"],
    "frame,x,y,z\ngeodetic,NaN,0,0\n",
  );
  assert.equal(result.status, 5, result.stderr);
  const row = JSON.parse(result.stdout);
  assert.equal(row.frame, "geodetic");
  assert.equal(row.thereabouts_query.declared_frame, "ecef");
});
