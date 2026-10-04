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
test("native preserves lossless cell integers and rejects invalid identifiers", async () => {
  const geo = await Geocoder.open({ pack });
  try {
    for (const [frame, cell] of [
      ["h3", 0x881fb46625fffffn],
      ["s2", 1n],
      ["s2", 0x89c2500000000001n],
    ]) {
      const hex =
        frame === "s2"
          ? cell.toString(16).padStart(16, "0")
          : cell.toString(16);
      const result = await geo.reversePoint({ frame, cell });
      assert.equal(result.query.error, null);
      assert.deepEqual(result, await geo.reversePoint({ frame, cell: hex }));
    }
    for (const frame of ["h3", "s2"])
      for (const cell of [0x881fb46625fffff, -1n, 1n << 64n]) {
        const result = await geo.reversePoint({ frame, cell });
        assert.equal(result.status, "invalid_input");
        assert.equal(result.query.error.code, "invalid_type");
      }
  } finally {
    await geo.close();
  }
});

test("adapter rejects API shapes, freezes metadata and preserves backpressure/lifetime", async () => {
  const geo = await Geocoder.open({ pack });
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
        yield {
          frame: "h3",
          cell: "881fb46625fffff",
          uncertainty: { hdop: 0.9 },
        };
      }
    } finally {
      released = true;
    }
  }
  const stream = geo.reversePoints(input(), { evidence: true });
  assert.deepEqual(seen, []);
  const { value: result } = await stream.next();
  assert.deepEqual(seen, [0]);
  assert.ok(result.evidence);
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
    for (const value of [NaN, Infinity, -Infinity, true, false, "1", 1n]) {
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
