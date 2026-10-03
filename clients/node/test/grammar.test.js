import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { description } from "../runtime/grammar.js";
import {
  ROOT,
  temporary,
  fixtureStore,
  selection,
  console,
  assertResult,
} from "./helpers.js";

function native(root, args, input = "") {
  return spawnSync(
    path.join(ROOT, ".venv/bin/thereabouts"),
    ["--data-dir", root, ...args],
    {
      input,
      encoding: "utf8",
      timeout: 30_000,
      env: process.env,
    },
  );
}
function parity(root, args, input = "") {
  const js = console(root, args, input),
    rust = native(root, args, input);
  const label = args.join(" ");
  assert.equal(js.status, rust.status, label);
  assert.equal(js.stdout, rust.stdout, label);
  assert.equal(js.stderr, rust.stderr, label);
  return js;
}

test("JSON grammar supplies identical native and Node help and argument errors", async (t) => {
  const root = temporary(t),
    grammar = await description();
  for (const command of grammar.commands) {
    for (const flag of command.options) assert.ok(flag.description, flag.name);
    const output = parity(root, [...command.name.split(" "), "--help"]);
    assert.equal(output.status, 0);
    for (const flag of command.options)
      assert.ok(output.stdout.includes(`--${flag.name}`));
  }
  for (const args of [
    [],
    ["--help"],
    ["--version"],
    ["--fields"],
    ["--bogus"],
    ["unknown"],
    ["data", "bogus"],
    ["data"],
    ["reverse", "--lat", "1"],
    ["reverse", "--lat", "bad", "--lon", "2"],
    ["geocode", "Paris", "--limit", "0"],
    ["geocode", "Paris", "--limit", "1.5"],
    ["geocode", "Paris", "--prefer", "bad"],
    ["postal", "75001"],
    ["ip", "1", "2"],
    ["info", "--json", "--csv"],
    ["info", "--format", "bad"],
    ["info", "--fields", "not_a_field"],
    ["info", "--quiet", "--quiet"],
    ["info", "--quiet=yes"],
    ["airport", "CDG", "--scheme", "bad"],
    ["data", "install"],
    ["data", "install", "core", "--version"],
    ["data", "update"],
  ])
    parity(root, args);
});

test("JSON rows preserve public, selected and source field order in both hosts", (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-sample"));
  const args = ["reverse", "--lat", "48.8566", "--lon", "2.3522"];
  for (const flag of ["--json", "--format=ndjson"]) {
    const full = console(root, [...args, flag]);
    const rust = native(root, [...args, flag]);
    assert.equal(full.status, 0, full.stderr);
    assert.equal(rust.status, 0, rust.stderr);
    assertResult(
      assert,
      JSON.parse(full.stdout),
      JSON.parse(rust.stdout),
      flag,
    );
    assert.deepEqual(
      Object.keys(JSON.parse(full.stdout)),
      Object.keys(JSON.parse(rust.stdout)),
    );
    assert.deepEqual(Object.keys(JSON.parse(full.stdout)).slice(0, 4), [
      "status",
      "kind",
      "match",
      "country",
    ]);
    const picked = parity(root, [...args, flag, "--fields=city.name,status"]);
    assert.deepEqual(Object.keys(JSON.parse(picked.stdout)), [
      "city.name",
      "status",
    ]);
  }
  const csv = "z,lon,lat,a\nfirst,2.3522,48.8566,last\n";
  const batch = parity(
    root,
    ["reverse", "-", "--fields=city.name,status"],
    csv,
  );
  assert.deepEqual(Object.keys(JSON.parse(batch.stdout)), [
    "z",
    "lon",
    "lat",
    "a",
    "thereabouts_city.name",
    "thereabouts_status",
  ]);
  const ndjson =
    '{"z":1,"lon":2.3522,"lat":48.8566}\n{"later":2,"lat":48.8566,"lon":2.3522}\n';
  const lines = parity(root, ["reverse", "-", "--fields=status"], ndjson)
    .stdout.trim()
    .split("\n")
    .map(JSON.parse);
  assert.deepEqual(Object.keys(lines[0]), [
    "z",
    "lon",
    "lat",
    "thereabouts_status",
  ]);
  assert.deepEqual(Object.keys(lines[1]), [
    "later",
    "lat",
    "lon",
    "thereabouts_status",
  ]);
  const tabular = parity(
    root,
    ["reverse", "-", "--csv", "--fields=status"],
    ndjson,
  );
  assert.equal(
    tabular.stdout.split("\n")[0],
    "z,lon,lat,later,thereabouts_status",
  );
});

test("info inventories keep the same family order in native and Node", (t) => {
  const root = temporary(t);
  fixtureStore(root, {
    ...selection("packs/postal-sample"),
    ...selection("packs/airports-sample"),
  });
  const info = parity(root, ["info", "--json"]);
  assert.equal(info.status, 0, info.stderr);
  assert.deepEqual(
    JSON.parse(info.stdout).packs.map((p) => p.family),
    ["core", "postal", "airports"],
  );
});

test("table pages measure later rows, use wide terminals and show invalid hints", (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-sample"));
  const previous = process.env.COLUMNS;
  t.after(() => {
    if (previous === undefined) delete process.env.COLUMNS;
    else process.env.COLUMNS = previous;
  });
  const region = "Wilayah Persekutuan Kuala Lumpur";
  const input = `id,lat,lon,region\n1,0,0,x\n2,1.3521,103.8198,${region}\n3,91,0,bad\n`;
  for (const width of [80, 220]) {
    process.env.COLUMNS = String(width);
    const result = parity(root, ["reverse", "-", "--format=table"], input);
    assert.equal(result.status, 5, result.stderr);
    assert.ok(
      result.stdout
        .trimEnd()
        .split("\n")
        .every((line) => [...line].length <= width),
    );
    assert.equal(result.stdout.match(/status/g).length, 1);
    assert.match(result.stdout, /hint:.*\[-90, 90\]/);
    if (width === 220) {
      assert.ok(result.stdout.includes("1.3521"));
      assert.ok(result.stdout.includes(region));
      assert.ok(!result.stdout.includes("…"));
    }
  }
});
