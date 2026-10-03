import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import fs from "node:fs";
import { run } from "../runtime/cli.js";
import { temporary, fixtureStore, selection, console } from "./helpers.js";
function host(input = "", tty = false) {
  let stdout = "",
    stderr = "";
  const lines = input.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  return {
    io: {
      stdout: (s) => (stdout += s),
      stderr: (s) => (stderr += s),
      readLine: () => lines.shift() ?? "",
      env: { ...process.env, NO_COLOR: "1" },
      stdinTTY: tty,
      stdoutTTY: tty,
    },
    out: () => stdout,
    err: () => stderr,
  };
}
test("every verb has help; bare help, version, fields and invalid flags need no data", async (t) => {
  for (const command of [
    "reverse",
    "h3",
    "geocode",
    "postal",
    "airport",
    "locode",
    "ip",
    "phone",
    "plate",
    "info",
    "mcp",
    "data",
    "data install",
    "data list",
    "data verify",
    "data remove",
    "data path",
    "data update",
  ]) {
    const h = host();
    assert.equal(await run([...command.split(" "), "--help"], h.io), 0);
    assert.match(h.out(), /--data-dir/);
    assert.match(h.out(), /--no-input/);
    if (command === "geocode")
      assert.ok(
        h
          .out()
          .startsWith(
            "Finds towns and cities by name. Street addresses are not supported.",
          ),
      );
  }
  for (const args of [
    [],
    ["--bogus"],
    ["reverse", "--lat", "1"],
    ["postal", "75001"],
    ["data", "update"],
    ["ip", "1", "--json", "--csv"],
  ]) {
    const h = host();
    assert.equal(await run(args, h.io), 2);
    assert.ok(h.err());
  }
  for (const args of [["--version"], ["--fields"]]) {
    const h = host();
    assert.equal(await run(args, h.io), 0);
    assert.ok(h.out());
  }
  const root = temporary(t),
    h = host();
  assert.equal(
    await run(
      ["--data-dir", root, "reverse", "--lat", "1", "--lon", "2"],
      h.io,
    ),
    3,
  );
  assert.equal(h.err().split("\n").at(-2), "thereabouts data install core");
});
test("shared table/JSON/NDJSON/CSV rendering and candidate indentation", async (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-names-sample"));
  for (const format of ["table", "json", "ndjson", "csv"]) {
    const h = host("", true);
    assert.equal(
      await run(
        ["--data-dir", root, "--format", format, "geocode", "Springfield"],
        h.io,
      ),
      0,
    );
    assert.ok(h.out());
    assert.ok(!h.out().includes("\x1b"));
    if (format === "table") {
      assert.match(h.out(), /status.*country.*state.*city.*point.*match/);
      assert.match(h.out(), /\n  /);
      assert.ok(!h.out().includes("evidence"));
    } else if (format !== "csv")
      assert.equal(JSON.parse(h.out()).status, "ambiguous");
  }
});
test("shared batches preserve input order, errors, quotes and late NDJSON columns", async (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-sample"));
  const csv =
    'z,lat,lon,a\n"quoted,\nline",48.8566,2.3522,first\nsecond,bad,4,last\n';
  const h = host(csv);
  assert.equal(
    await run(
      [
        "--data-dir",
        root,
        "reverse",
        "-",
        "--csv",
        "--fields",
        "city.name,status",
      ],
      h.io,
    ),
    5,
  );
  assert.equal(
    h.out().split("\n")[0],
    "z,lat,lon,a,thereabouts_city.name,thereabouts_status",
  );
  assert.match(h.out(), /"quoted,\nline"/);
  assert.match(h.out(), /invalid_input/);
  const late = host(
    '{"lat":48.8566,"lon":2.3522,"z":"first"}\n{"lat":48.8566,"lon":2.3522,"later":3}\n',
  );
  assert.equal(
    await run(["--data-dir", root, "reverse", "-", "--csv"], late.io),
    0,
  );
  assert.match(late.out().split("\n")[0], /later/);
  const input = path.join(root, "points.csv");
  fs.writeFileSync(input, csv);
  const actual = console(root, ["reverse", input, "--json"]);
  assert.equal(actual.status, 5);
  assert.equal(JSON.parse(actual.stdout).results.length, 2);
  const piped = console(
    root,
    ["reverse", "-", "--fields", "status"],
    "lat,lon\n48.8566,2.3522\n",
  );
  assert.equal(piped.status, 0, piped.stderr);
  assert.equal(JSON.parse(piped.stdout).thereabouts_status, "matched");
});
test("strict miss, invalid scalar, missing file and corrupt pack exit policies", async (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-synthetic"));
  for (const [args, code] of [
    [["reverse", "--lat", "0", "--lon", "0", "--strict"], 1],
    [["reverse", "--lat", "91", "--lon", "0"], 2],
    [["reverse", path.join(root, "absent.csv")], 2],
  ]) {
    const h = host();
    assert.equal(await run(["--data-dir", root, ...args], h.io), code, h.err());
  }
  const pin = JSON.parse(fs.readFileSync(path.join(root, "active.json")));
  pin.packs.core.manifest_sha256 = "0".repeat(64);
  fs.writeFileSync(path.join(root, "active.json"), JSON.stringify(pin));
  const h = host();
  assert.equal(
    await run(["--data-dir", root, "h3", "8860140001fffff"], h.io),
    4,
  );
  assert.match(h.err(), /data verify --full/);
  assert.match(h.err(), /packs\/core/);
});

test("broken output pipes exit zero across the WASM error boundary", async (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-synthetic"));
  const h = host();
  h.io.stdout = () => {
    throw Object.assign(new Error("Broken pipe"), { code: "EPIPE" });
  };
  assert.equal(
    await run(["--data-dir", root, "h3", "8860140001fffff"], h.io),
    0,
  );
  assert.equal(h.err(), "");
});

test("tables respect terminal columns and keep batch result headers readable", async (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-sample"));
  for (const columns of [80, 120]) {
    const h = host(
      "id,lat,lon,note\n1,48.8566,2.3522,A very long note that needs truncation\n",
      true,
    );
    h.io.env.COLUMNS = String(columns);
    assert.equal(
      await run(["--data-dir", root, "reverse", "-"], h.io),
      0,
      h.err(),
    );
    assert.ok(
      h
        .out()
        .trimEnd()
        .split("\n")
        .every((s) => [...s].length <= columns),
    );
    assert.match(
      h.out().split("\n")[0],
      /status.*country.*state.*city.*timezone.*point.*match/,
    );
    assert.ok(!h.out().includes("thereabou"));
  }
});

test("version output follows the packaged metadata", async () => {
  const metadata = JSON.parse(
    fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  );
  const h = host();
  assert.equal(await run(["--version"], h.io), 0);
  assert.equal(h.out(), `thereabouts ${metadata.version}\n`);
});
