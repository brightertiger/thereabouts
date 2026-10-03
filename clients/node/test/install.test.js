import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { spawnSync } from "node:child_process";
import { install, lock, remove } from "../runtime/install.js";
import { source, select, compareVersions } from "../runtime/transport.js";
import { active, installed } from "../runtime/store.js";
import { run } from "../runtime/cli.js";
import { extract } from "../runtime/archive.js";
import { Geocoder } from "../runtime/index.js";
import { release, tar } from "./release.js";
import { temporary, console, ROOT } from "./helpers.js";
async function server(t, handler) {
  const service = http.createServer(handler);
  await new Promise((resolve) => service.listen(0, "127.0.0.1", resolve));
  t.after(
    () =>
      new Promise((resolve) => {
        service.closeAllConnections();
        service.close(resolve);
      }),
  );
  return new URL(`http://127.0.0.1:${service.address().port}/`);
}
test("local install is idempotent, discovers and verifies before atomic activation", async (t) => {
  const root = temporary(t),
    origin = path.join(root, "release"),
    store = path.join(root, "store");
  const { version } = release(origin);
  const pin = await install(store, origin, ["phone"]);
  assert.equal(pin.data_version, version);
  assert.deepEqual(await install(store, origin, ["phone"]), pin);
  assert.equal(active(store).packs.phone.path, `packs/phone/${version}`);
  const geo = await Geocoder.open({ dataDir: store });
  assert.equal((await geo.phone("+32 2 555 1234")).status, "matched");
  geo.close();
  for (const args of [
    ["data", "list"],
    ["data", "verify"],
    ["data", "verify", "--full"],
    ["info"],
    ["data", "path"],
  ]) {
    const value = console(store, [...args, "--json"]);
    assert.equal(value.status, 0, value.stderr);
    assert.ok(JSON.parse(value.stdout));
  }
  const missingConsent = console(store, ["data", "remove", "phone"]);
  assert.equal(missingConsent.status, 2);
  const removed = console(store, ["data", "remove", "phone", "--yes"]);
  assert.equal(removed.status, 0, removed.stderr);
  assert.deepEqual(active(store).packs, {});
});
test("loopback interrupted download resumes with exact Range and integrity verification", async (t) => {
  const root = temporary(t),
    fixture = release(path.join(root, "release")),
    store = path.join(root, "store");
  let first = true;
  const ranges = [];
  const origin = await server(t, (request, response) => {
    if (request.url === "/index.json") {
      response.end(JSON.stringify(fixture.index));
      return;
    }
    assert.equal(request.headers["accept-encoding"], "identity");
    ranges.push(request.headers.range ?? null);
    if (first) {
      first = false;
      response.writeHead(200, { "Content-Length": fixture.bytes.length });
      response.write(fixture.bytes.subarray(0, 1024));
      setTimeout(() => response.destroy(), 30);
      return;
    }
    const offset = Number(
      request.headers.range?.match(/^bytes=(\d+)-$/)?.[1] ?? 0,
    );
    response.writeHead(offset ? 206 : 200, {
      "Content-Length": fixture.bytes.length - offset,
      ...(offset
        ? {
            "Content-Range": `bytes ${offset}-${fixture.bytes.length - 1}/${fixture.bytes.length}`,
          }
        : {}),
    });
    response.end(fixture.bytes.subarray(offset));
  });
  await assert.rejects(install(store, origin, ["phone"]), {
    exitCode: 2,
    message: /Download interrupted; run the same data install again to resume/,
  });
  assert.equal(active(store), null);
  const partial = path.join(store, ".downloads", fixture.pack.sha256 + ".part");
  assert.equal(fs.statSync(partial).size, 1024);
  await install(store, origin, ["phone"]);
  assert.deepEqual(ranges, [null, "bytes=1024-"]);
  assert.ok(await installed(store, "phone"));
  assert.ok(!fs.existsSync(partial));
});
test("checksum, ignored ranges and atomic version guard preserve existing pins", async (t) => {
  const root = temporary(t),
    origin = path.join(root, "release"),
    fixture = release(origin),
    store = path.join(root, "store");
  await install(store, origin, ["phone"]);
  const before = fs.readFileSync(path.join(store, "active.json"), "utf8");
  const badRoot = path.join(root, "bad");
  const wrong = structuredClone(fixture.index);
  wrong.datasets[fixture.version].packs.phone.sha256 = "0".repeat(64);
  fs.writeFileSync(path.join(origin, "index.json"), JSON.stringify(wrong));
  await assert.rejects(install(badRoot, origin, ["phone"]), /checksum/);
  assert.equal(active(badRoot), null);
  assert.ok(
    !fs.existsSync(path.join(badRoot, ".downloads", "0".repeat(64) + ".part")),
  );
  const changed = {
    format: 2,
    datasets: { 2099.1: { packs: { core: fixture.pack } } },
  };
  fs.writeFileSync(path.join(origin, "index.json"), JSON.stringify(changed));
  await assert.rejects(install(store, origin, ["core"]), /every active family/);
  assert.equal(
    fs.readFileSync(path.join(store, "active.json"), "utf8"),
    before,
  );
  const rangeStore = path.join(root, "range");
  fs.mkdirSync(path.join(rangeStore, ".downloads"), { recursive: true });
  const partial = path.join(
    rangeStore,
    ".downloads",
    fixture.pack.sha256 + ".part",
  );
  fs.writeFileSync(partial, fixture.bytes.subarray(0, 100));
  const httpOrigin = await server(t, (request, response) =>
    response.end(
      request.url === "/index.json"
        ? JSON.stringify(fixture.index)
        : fixture.bytes,
    ),
  );
  await assert.rejects(
    install(rangeStore, httpOrigin, ["phone"]),
    /resume range/,
  );
  assert.equal(fs.statSync(partial).size, 100);
});
test("OS advisory lock serializes Node and native installs and releases on close", async (t) => {
  const root = temporary(t),
    origin = path.join(root, "release"),
    store = path.join(root, "store");
  release(origin);
  const unlock = await lock(store);
  await assert.rejects(lock(store), /Install lock/);
  await assert.rejects(install(store, origin, ["phone"]), /[Ii]nstall lock/);
  const native = spawnSync(
    path.join(ROOT, ".venv/bin/thereabouts"),
    ["--data-dir", store, "data", "remove", "phone", "--yes"],
    { encoding: "utf8", env: process.env },
  );
  assert.equal(native.status, 4, native.stderr);
  assert.match(native.stderr, /[Ii]nstall lock/);
  await unlock();
  await install(store, origin, ["phone"]);
  await remove(store, "phone");
});
test("placeholder fails before transfer; index ordering and prompts match native policy", async (t) => {
  assert.throws(() => source(undefined, {}), /--from.*THEREABOUTS_RELEASE_URL/);
  for (const url of [
    "http://name:secret@127.0.0.1/",
    "http://127.0.0.1/#fragment",
    "http://[",
  ]) {
    assert.throws(
      () => source(url),
      (e) => e.exitCode === 2,
    );
  }
  assert.ok(compareVersions("2026.10", "2026.9") > 0);
  const root = temporary(t),
    origin = path.join(root, "release"),
    fixture = release(origin),
    store = path.join(root, "store");
  assert.equal(select(fixture.index, ["phone"])[0], fixture.version);
  await install(store, origin, ["phone"]);
  for (const [answer, expected] of [
    ["n\n", 2],
    ["yes\n", 0],
  ]) {
    let output = "",
      error = "";
    const code = await run(["--data-dir", store, "data", "remove", "phone"], {
      stdout: (s) => (output += s),
      stderr: (s) => (error += s),
      readLine: () => answer,
      stdinTTY: true,
      stdoutTTY: false,
      env: process.env,
    });
    assert.equal(code, expected);
    assert.match(error, /\[y\/N\]/);
    if (!code) assert.equal(JSON.parse(output).removed, "phone");
  }
});
test("strict ustar rejects links, traversal, duplicates, trailers and truncation", (t) => {
  const root = temporary(t);
  const invalid = [
    tar([["../escape", Buffer.from("x")]]),
    tar([["link", Buffer.alloc(0), "2"]]),
    tar([
      ["one", Buffer.from("a")],
      ["one", Buffer.from("b")],
    ]),
    tar([[".archive.json", Buffer.from("{}")]]),
    Buffer.alloc(512),
    Buffer.concat([tar([]), Buffer.from([1])]),
  ];
  for (const [i, bytes] of invalid.entries()) {
    const file = path.join(root, i + ".tar"),
      out = path.join(root, "out-" + i);
    fs.writeFileSync(file, bytes);
    fs.mkdirSync(out);
    assert.throws(() => extract(file, out, bytes.length));
  }
  assert.ok(!fs.existsSync(path.join(root, "escape")));
});

test("two-family failure leaves the old activation untouched; remote list/update are explicit", async (t) => {
  const root = temporary(t),
    origin = path.join(root, "release"),
    store = path.join(root, "store");
  const phone = release(origin, "phone"),
    postal = release(origin, "postal");
  const value = phone.index;
  value.datasets[phone.version].packs.postal = {
    ...postal.pack,
    sha256: "0".repeat(64),
  };
  fs.writeFileSync(path.join(origin, "index.json"), JSON.stringify(value));
  await assert.rejects(install(store, origin, ["phone", "postal"]), /checksum/);
  assert.equal(active(store), null);
  await install(store, origin, ["phone"]);
  for (const args of [
    ["data", "list", "--remote"],
    ["data", "update", "--check"],
  ]) {
    const result = console(store, [...args, "--json"], "", {
      THEREABOUTS_RELEASE_URL: origin,
    });
    assert.equal(result.status, 0, result.stderr);
    const parsed = JSON.parse(result.stdout);
    if (args[1] === "update") assert.equal(parsed.update_available, false);
    else assert.equal(parsed.format, 2);
  }
});

test("process termination releases shared coordination without stale cleanup", async (t) => {
  const { spawn } = await import("node:child_process");
  const { once } = await import("node:events");
  const root = temporary(t);
  const script =
    'import {lock} from "./clients/node/runtime/install.js"; await lock(process.argv[1]); process.stdout.write("ready\\n"); setInterval(() => {}, 1000);';
  const child = spawn(
    process.execPath,
    ["--input-type=module", "-e", script, root],
    { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"], env: process.env },
  );
  t.after(() => child.kill("SIGKILL"));
  const [bytes] = await once(child.stdout, "data");
  assert.ok(bytes.toString().startsWith("ready"));
  await assert.rejects(lock(root), /[Ii]nstall lock/);
  child.kill("SIGKILL");
  await once(child, "close");
  const releaseLock = await lock(root);
  await releaseLock();
});
