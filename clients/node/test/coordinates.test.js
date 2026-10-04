import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { Geocoder } from "../runtime/geocoder.js";
import { ClosedGeocoderError } from "../runtime/errors.js";
import { wasm } from "../runtime/wasm.js";
import { FIXTURES, assertResult } from "./helpers.js";

const pack = path.join(FIXTURES, "packs/core-sample");
const invalidNumber = { __thereabouts_invalid_number__: true };
function facade() {
  const calls = [];
  const handle = {
    reversePoint(request, evidence) {
      calls.push({ request: JSON.parse(request), evidence });
      return JSON.stringify({
        query: {
          conversion: [],
          uncertainty: { hdop: 0.9 },
          cell_extent: { boundary: [{ lat: 1, lon: 2 }] },
        },
      });
    },
    free() {},
  };
  return {
    calls,
    geo: new Geocoder(
      { Geocoder: { open: () => handle } },
      { core: pack },
      false,
    ),
  };
}

test("adapter preserves invalid optional numbers and lossless cell integers", async () => {
  const { geo, calls } = facade();
  for (const value of [NaN, Infinity, -Infinity, true, false, 1n]) {
    await geo.reversePoint({
      lat: 0,
      lon: 0,
      height: value,
      geoid_separation: value,
      uncertainty: { accuracy_m: value, hdop: value, vdop: value },
    });
    const { request } = calls.at(-1);
    assert.deepEqual(request.height, invalidNumber);
    assert.deepEqual(request.geoid_separation, invalidNumber);
    for (const item of Object.values(request.uncertainty))
      assert.deepEqual(item, invalidNumber);
  }
  await geo.reversePoint({ frame: "h3", cell: 0x881fb46625fffffn });
  assert.equal(calls.at(-1).request.cell, "881fb46625fffff");
  await geo.reversePoint({ frame: "s2", cell: 1n });
  assert.equal(calls.at(-1).request.cell, "0000000000000001");
  await geo.reversePoint({ frame: "s2", cell: 0x89c2500000000001n });
  assert.equal(calls.at(-1).request.cell, "89c2500000000001");
  for (const cell of [0x881fb46625fffff, -1n, 1n << 64n]) {
    await geo.reversePoint({ frame: "s2", cell });
    assert.deepEqual(calls.at(-1).request.cell, invalidNumber);
  }
  await geo.close();
});

test("adapter rejects API shapes, freezes metadata and preserves backpressure/lifetime", async () => {
  const { geo, calls } = facade();
  for (const point of [[1, 2, 3], null, 1, new Date()])
    await assert.rejects(geo.reversePoint(point), TypeError);
  await assert.rejects(
    geo.reversePoint({ lat: 0, lon: 0 }, { evidence: 1 }),
    TypeError,
  );
  await assert.rejects(
    geo.reversePoint({ lat: 0, lon: 0 }, { extra: 1 }),
    TypeError,
  );
  const seen = [];
  let released = false;
  async function* input() {
    try {
      for (let i = 0; i < 3; i++) {
        seen.push(i);
        yield { lat: i, lon: 0 };
      }
    } finally {
      released = true;
    }
  }
  const stream = geo.reversePoints(input(), { evidence: true });
  assert.deepEqual(seen, []);
  const { value: result } = await stream.next();
  assert.deepEqual(seen, [0]);
  assert.equal(calls[0].evidence, true);
  assert.throws(() => result.query.conversion.push("guessed"), TypeError);
  assert.throws(() => {
    result.query.uncertainty.hdop = 1;
  }, TypeError);
  assert.throws(() => {
    result.query.cell_extent.boundary[0].lat = 0;
  }, TypeError);
  await geo.close();
  await assert.rejects(stream.next(), ClosedGeocoderError);
  assert.deepEqual(seen, [0]);
  assert.equal(released, true);
  await assert.rejects(
    geo.reversePoint({ lat: 0, lon: 0 }),
    ClosedGeocoderError,
  );
});

test("native framed results preserve old keys, exact input and uncertainty", async () => {
  const geo = await Geocoder.open({ pack });
  try {
    const input = {
      lat: 48.8566,
      lon: 2.3522,
      uncertainty: { accuracy_m: 4, hdop: 0.9, vdop: 1.2 },
    };
    const { query, ...result } = await geo.reversePoint(input);
    assert.deepEqual(result, await geo.reverse(input));
    assert.equal(query.declared_frame, null);
    assert.equal(query.normalized.lat, input.lat);
    assert.equal(query.normalized.lon, input.lon);
    assert.notDeepEqual(result.point, { lat: input.lat, lon: input.lon });
    assert.deepEqual(query.uncertainty, input.uncertainty);
    assert.equal(result.evidence, undefined);
    assert.ok((await geo.reversePoint(input, { evidence: true })).evidence);
    for (const value of [NaN, Infinity, -Infinity, true, "1"]) {
      for (const field of [
        "height",
        "geoid_separation",
        "accuracy_m",
        "hdop",
        "vdop",
      ]) {
        const point = { lat: 0, lon: 0 };
        if (["height", "geoid_separation"].includes(field))
          point[field] = value;
        else point.uncertainty = { [field]: value };
        const invalid = await geo.reversePoint(point);
        assert.equal(invalid.status, "invalid_input");
        assert.equal(invalid.query.error.code, "invalid_type");
        assert.equal(invalid.query.normalized, null);
      }
    }
    const s2 = await geo.reversePoint({
      frame: "s2",
      cell: 0x89c2500000000001n,
    });
    assert.deepEqual(
      s2,
      await geo.reversePoint({ frame: "s2", cell: "89c2500000000001" }),
    );
    assert.equal(
      (
        await geo.reversePoint({
          frame: "s2",
          cell: Number(0x89c2500000000001n),
        })
      ).query.error.code,
      "invalid_type",
    );
    const ordered = [];
    for await (const row of geo.reversePoints([
      { lat: 2, lon: 0 },
      { lat: 91, lon: 0 },
      { lat: 1, lon: 0 },
    ]))
      ordered.push(row);
    assert.deepEqual(
      ordered.map((row) => row.query.normalized?.lat ?? null),
      [2, null, 1],
    );
    const equator = await geo.reversePoint({
      frame: "ecef",
      x: 6378137,
      y: 0,
      z: 0,
    });
    assert.equal(equator.query.normalized.lat, 0);
    assert.equal(equator.query.normalized.lon, 0);
    for (const cell of ["801ffffffffffff", "881fb46625fffff"]) {
      const { query: h3Query, ...value } = await geo.reversePoint({
        frame: "h3",
        cell,
      });
      assert.deepEqual(value, await geo.fromH3(cell));
      assert.ok(h3Query.cell_extent);
      assert.deepEqual(
        await geo.reversePoint({ frame: "h3", cell: BigInt("0x" + cell) }),
        { ...value, query: h3Query },
      );
    }
    const invalid = await geo.reversePoint({
      frame: "h3",
      cell: "891fb466257ffff",
    });
    assert.equal(invalid.query.error.code, "unsupported_cell_resolution");
    const native = (await wasm()).Geocoder.open(pack, false);
    try {
      assert.equal(
        JSON.parse(native.reversePoint("{", false)).query.error.code,
        "invalid_syntax",
      );
    } finally {
      native.free();
    }
  } finally {
    await geo.close();
  }
});

function assertVector(actual, expected, tolerances, prefix = "") {
  if (Array.isArray(expected)) {
    assert.equal(actual.length, expected.length, prefix);
    expected.forEach((item, i) =>
      assertVector(actual[i], item, tolerances, `${prefix}.*`),
    );
  } else if (expected && typeof expected === "object") {
    for (const [key, value] of Object.entries(expected))
      assertVector(
        actual[key],
        value,
        tolerances,
        prefix ? `${prefix}.${key}` : key,
      );
  } else if (typeof expected === "number") {
    // Same angular comparison as the core fixture runner, including ±180.
    let delta = actual - expected;
    if (prefix.endsWith(".lon"))
      delta = ((((delta + 180) % 360) + 360) % 360) - 180;
    assert.ok(
      Math.abs(delta) <= (tolerances[prefix] ?? 0),
      `${prefix}: ${actual} vs ${expected}`,
    );
  } else assert.deepEqual(actual, expected, prefix);
}
function assertSchema(actual, expected) {
  if (expected === null) {
    assert.equal(actual, null);
    return;
  }
  assert.equal(typeof actual, typeof expected);
  if (typeof expected !== "object") return;
  assert.equal(Array.isArray(actual), Array.isArray(expected));
  assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort());
  for (const key of Object.keys(expected))
    assertSchema(actual[key], expected[key]);
}

test("shared vectors cover every frame in WASM and agree with native Python", async () => {
  const fixture = path.join(FIXTURES, "coordinates/vectors.json");
  const vectors = JSON.parse(fs.readFileSync(fixture, "utf8"));
  assert.equal(vectors.schema_version, 1);
  const processResult = spawnSync(
    process.env.THEREABOUTS_PYTHON ?? "python3",
    [
      "-c",
      "import json,sys; from thereabouts import Geocoder; v=json.load(open(sys.argv[1])); g=Geocoder(sys.argv[2]); json.dump([g.reverse_point(c['input']).to_dict() for c in v['cases']],sys.stdout); g.close()",
      fixture,
      pack,
    ],
    { encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } },
  );
  assert.equal(
    processResult.status,
    0,
    processResult.stderr || String(processResult.error),
  );
  const native = JSON.parse(processResult.stdout);
  const geo = await Geocoder.open({ pack });
  const frames = new Set();
  try {
    for (const [i, vector] of vectors.cases.entries()) {
      frames.add(vector.input.frame ?? "geodetic");
      const { query, ...result } = await geo.reversePoint(vector.input);
      const { query: nativeQuery, ...nativeResult } = native[i];
      assertResult(assert, result, nativeResult, vector.id);
      assertSchema(query, nativeQuery);
      assert.deepEqual(
        Object.keys(query).sort(),
        [
          "input_frame",
          "declared_frame",
          "normalized",
          "origin",
          "conversion",
          "source_height",
          "uncertainty",
          "cell_extent",
          "nmea",
          "error",
        ].sort(),
      );
      for (const key of [
        "input_frame",
        "declared_frame",
        "origin",
        "conversion",
        "source_height",
        "uncertainty",
        "nmea",
        "error",
      ])
        assert.deepEqual(query[key], nativeQuery[key], vector.id + "." + key);
      if (vector.expected.error) {
        assert.equal(result.status, "invalid_input", vector.id);
        assert.equal(query.error.code, vector.expected.error, vector.id);
        assert.equal(query.error.message, result.hint);
        assert.equal(query.normalized, null);
      } else {
        assert.equal(query.error, null, vector.id);
        assertVector(query, vector.expected, vector.tolerance);
        assertVector(
          { normalized: query.normalized },
          { normalized: nativeQuery.normalized },
          vector.tolerance,
        );
        assert.deepEqual(
          result,
          vector.input.frame === "h3"
            ? await geo.fromH3(vector.input.cell)
            : await geo.reverse(query.normalized),
        );
      }
    }
    for (const frame of [
      "geodetic",
      "ecef",
      "enu",
      "ned",
      "utm",
      "mgrs",
      "geohash",
      "pluscode",
      "h3",
      "s2",
      "dms",
      "nmea",
      "geojson",
      "wkt",
    ])
      assert.ok(frames.has(frame));
  } finally {
    await geo.close();
  }
});

test("adapter build script uses the supplied target for cargo and bindgen", (t) => {
  const root = path.resolve(FIXTURES, "../..");
  const cache = path.join(root, ".cache");
  fs.mkdirSync(cache, { recursive: true });
  const scratch = fs.mkdtempSync(path.join(cache, "coords-build-script-"));
  t.after(() => fs.rmSync(scratch, { recursive: true, force: true }));
  const script = path.join(scratch, "clients/node/scripts/build-wasm.mjs");
  fs.mkdirSync(path.dirname(script), { recursive: true });
  fs.copyFileSync(
    new URL("../scripts/build-wasm.mjs", import.meta.url),
    script,
  );
  const bin = path.join(scratch, "bin");
  fs.mkdirSync(bin);
  const fake = path.join(bin, "cargo");
  fs.writeFileSync(
    fake,
    `#!${process.execPath}\nconst fs = require("node:fs"); fs.appendFileSync(process.env.COORDS_TEST_LOG, JSON.stringify({target: process.env.CARGO_TARGET_DIR, args: process.argv.slice(2)}) + "\\n");\n`,
    { mode: 0o755 },
  );
  // The subprocess tools are facades; no target tree is built here.
  const target = process.env.CARGO_TARGET_DIR ?? path.join(scratch, "target");
  const absolute = path.resolve(root, target);
  for (const supplied of [absolute, path.relative(scratch, absolute)]) {
    const log = path.join(scratch, "calls.jsonl");
    fs.writeFileSync(log, "");
    const child = spawnSync(process.execPath, [script], {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${bin}${path.delimiter}${process.env.PATH}`,
        CARGO_TARGET_DIR: supplied,
        WASM_BINDGEN: fake,
        COORDS_TEST_LOG: log,
      },
    });
    assert.equal(child.status, 0, child.stderr);
    const calls = fs
      .readFileSync(log, "utf8")
      .trim()
      .split("\n")
      .map(JSON.parse);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].target, absolute);
    assert.equal(calls[1].target, absolute);
    assert.equal(
      calls[1].args.at(-1),
      path.join(
        absolute,
        "wasm32-unknown-unknown/release/thereabouts_wasm.wasm",
      ),
    );
  }
});
