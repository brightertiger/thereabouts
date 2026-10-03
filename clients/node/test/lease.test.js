import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { lock } from "../runtime/lease.js";
import { wasm } from "../runtime/wasm.js";
import { temporary, ROOT } from "./helpers.js";
const record = (pid, token = "a".repeat(32)) =>
  JSON.stringify({ pid, created_ms: 1, token });
function deadPid() {
  const child = spawnSync(process.execPath, ["-e", ""], { env: process.env });
  assert.equal(child.status, 0);
  return child.pid;
}
test("live leases never age out; recent partial records wait and old ones recover", async (t) => {
  const root = temporary(t),
    marker = path.join(root, ".lock");
  fs.writeFileSync(marker, record(process.pid));
  fs.utimesSync(marker, 1, 1);
  await assert.rejects(lock(root), {
    exitCode: 2,
    message: /Another install is running/,
  });
  fs.writeFileSync(marker, "");
  await assert.rejects(lock(root), { exitCode: 2 });
  fs.utimesSync(marker, 1, 1);
  const release = await lock(root);
  assert.equal(JSON.parse(fs.readFileSync(marker)).pid, process.pid);
  await release();
  assert.ok(!fs.existsSync(marker));
  fs.mkdirSync(marker);
  await assert.rejects(lock(root), { exitCode: 4 });
});

test("Node and native recover a dead reaper without removing a successor", async (t) => {
  const core = await wasm();
  for (const native of [false, true]) {
    const root = temporary(t),
      original = record(deadPid());
    fs.writeFileSync(path.join(root, ".lock"), original);
    fs.writeFileSync(
      path.join(root, core.lockRecoveryName(".lock", original)),
      record(deadPid(), "b".repeat(32)),
    );
    if (native) {
      const result = spawnSync(
        path.join(ROOT, ".venv/bin/thereabouts"),
        ["--data-dir", root, "data", "remove", "phone", "--yes"],
        { encoding: "utf8", env: process.env },
      );
      assert.equal(result.status, 0, result.stderr);
    } else {
      const release = await lock(root);
      // Release cannot remove a different lease incarnation.
      fs.writeFileSync(path.join(root, ".lock"), record(process.pid));
      await release();
      assert.equal(
        fs.readFileSync(path.join(root, ".lock"), "utf8"),
        record(process.pid),
      );
      fs.unlinkSync(path.join(root, ".lock"));
    }
    assert.ok(!fs.readdirSync(root).some((name) => name.startsWith(".lock")));
  }
});

test(
  "competing stale takeovers never overlap their critical sections",
  { timeout: 20_000 },
  async (t) => {
    const root = temporary(t);
    fs.writeFileSync(path.join(root, ".lock"), record(deadPid()));
    const code = `
    import fs from 'node:fs';
    import {lock} from './clients/node/runtime/lease.js';
    try {
      const root=process.argv[1], release=await lock(root);
      const fd=fs.openSync(root+'/critical','wx');
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,150);
      fs.closeSync(fd); fs.unlinkSync(root+'/critical'); await release();
    } catch(e) { process.stderr.write(e.message); process.exitCode=e.exitCode??1; }
  `;
    const results = await Promise.all(
      Array.from(
        { length: 8 },
        () =>
          new Promise((resolve, reject) => {
            const child = spawn(
              process.execPath,
              ["--input-type=module", "-e", code, root],
              {
                cwd: ROOT,
                env: process.env,
                stdio: ["ignore", "pipe", "pipe"],
              },
            );
            t.after(() => child.kill());
            let stderr = "";
            child.stderr.on("data", (b) => {
              stderr += b;
            });
            child.on("error", reject);
            child.on("close", (code) => {
              assert.ok([0, 2].includes(code), stderr);
              resolve(code);
            });
          }),
      ),
    );
    assert.ok(results.includes(0));
    assert.ok(!fs.existsSync(path.join(root, ".lock")));
  },
);
