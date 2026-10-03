import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { writeAll } from "../runtime/output.js";
import { run } from "../runtime/cli.js";
import { sha256 } from "../runtime/store.js";
import {
  temporary,
  fixtureStore,
  selection,
  console,
  BIN,
  FIXTURES,
} from "./helpers.js";

test("sinks handle partial UTF-8 writes, interrupts and backpressure", () => {
  const chunks = [];
  let call = 0;
  writeAll(1, "Paris → 東京", (_fd, bytes, offset, length) => {
    const code = ["EINTR", "EAGAIN", "EWOULDBLOCK"][call++];
    if (code) throw Object.assign(new Error(code), { code });
    const count = Math.min(2, length);
    chunks.push(bytes.subarray(offset, offset + count));
    return count;
  });
  assert.equal(Buffer.concat(chunks).toString(), "Paris → 東京");
  assert.throws(() => writeAll(1, "x", () => 0), { code: "EIO", exitCode: 2 });
});

async function delayedOutput(t, root, args) {
  const child = spawn(
    process.execPath,
    [
      "--import",
      new URL("./offline.js", import.meta.url).pathname,
      BIN,
      "--data-dir",
      root,
      ...args,
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  t.after(() => child.kill());
  const stdout = [],
    stderr = [];
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const done = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => resolve(code));
  });
  // Leave the child's pipe unread long enough to fill its kernel buffer.
  await delay(1000);
  child.stdout.on("data", (chunk) => stdout.push(chunk));
  assert.equal(await done, 0, Buffer.concat(stderr).toString());
  assert.equal(Buffer.concat(stderr).length, 0);
  return Buffer.concat(stdout).toString();
}

test(
  "slow pipe preserves info JSON over 256 KiB and all 3,000 batch rows",
  { timeout: 30_000 },
  async (t) => {
    const root = temporary(t);
    fixtureStore(
      root,
      Object.fromEntries(
        ["core", "postal", "airports", "locode", "phone", "ip", "plates"].map(
          (family) => [family, path.join(FIXTURES, `packs/${family}-sample`)],
        ),
      ),
    );
    // Enlarge only the temporary manifest, detaching its hard link first.
    const pinPath = path.join(root, "active.json");
    const pin = JSON.parse(fs.readFileSync(pinPath));
    const manifestPath = path.join(root, pin.packs.core.path, "manifest.json");
    const manifest = JSON.parse(fs.readFileSync(manifestPath));
    manifest.attribution += "Synthetic pipe-test attribution. ".repeat(10_000);
    fs.unlinkSync(manifestPath);
    fs.writeFileSync(manifestPath, JSON.stringify(manifest));
    pin.packs.core.manifest_sha256 = sha256(manifestPath);
    fs.writeFileSync(pinPath, JSON.stringify(pin));
    const expected = console(root, ["info", "--json"]);
    assert.equal(expected.status, 0, expected.stderr);
    assert.ok(Buffer.byteLength(expected.stdout) >= 256 * 1024);
    assert.equal(
      await delayedOutput(t, root, ["info", "--json"]),
      expected.stdout,
    );
    const input = path.join(root, "big.csv");
    fs.writeFileSync(
      input,
      "id,lat,lon\n" +
        Array.from({ length: 3000 }, (_, i) => `${i},48.8566,2.3522\n`).join(
          "",
        ),
    );
    const lines = (await delayedOutput(t, root, ["reverse", input]))
      .trimEnd()
      .split("\n");
    assert.equal(lines.length, 3000);
    lines.forEach((line, i) => {
      const row = JSON.parse(line);
      assert.equal(row.id, String(i));
      assert.equal(row.thereabouts_status, "matched");
    });
  },
);

test("output IO failure is an environment error without pack repair advice", async (t) => {
  const root = temporary(t);
  fixtureStore(root, selection("packs/core-synthetic"));
  let stderr = "";
  assert.equal(
    await run(["--data-dir", root, "h3", "8860140001fffff"], {
      stdout: () => {
        throw Object.assign(new Error("Output device failed"), { code: "EIO" });
      },
      stderr: (s) => {
        stderr += s;
      },
      env: {},
      stdinTTY: false,
      stdoutTTY: false,
    }),
    2,
  );
  assert.match(stderr, /Output device failed/);
  assert.doesNotMatch(stderr, /pack|reinstall|verify/);
});
