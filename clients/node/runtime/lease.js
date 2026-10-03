// Exclusive file leases. PID probing is host-owned; wire policy/names come from Rust.
import fs from "node:fs";
import { randomBytes } from "node:crypto";
import { safePath } from "./host.js";
import { usage, integrity } from "./errors.js";
import { wasm } from "./wasm.js";
const busy = () => usage("Another install is running; retry after it finishes");
export async function lock(root) {
  fs.mkdirSync(root, { recursive: true });
  const core = await wasm(),
    policy = JSON.parse(core.lockPolicy());
  function snapshot(filename) {
    let fd;
    try {
      fd = fs.openSync(
        filename,
        fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0),
      );
    } catch (e) {
      if (e.code === "ENOENT") return null;
      throw e;
    }
    try {
      const stat = fs.fstatSync(fd);
      if (!stat.isFile() || stat.size > policy.max_bytes)
        throw integrity("Invalid store lock file");
      const buffer = Buffer.alloc(policy.max_bytes + 1);
      const count = fs.readSync(fd, buffer, 0, buffer.length, 0);
      if (count > policy.max_bytes)
        throw integrity("Oversized store lock file");
      let contents;
      try {
        contents = new TextDecoder("utf-8", { fatal: true }).decode(
          buffer.subarray(0, count),
        );
      } catch {
        throw integrity("Non-UTF8 store lock file");
      }
      return { contents, modified: stat.mtimeMs };
    } finally {
      fs.closeSync(fd);
    }
  }
  function stale(record) {
    const value = JSON.parse(
      core.lockState(record.contents, record.modified, Date.now()),
    );
    if (value.state !== "owner") return value.state === "abandoned";
    try {
      process.kill(value.pid, 0);
      return false;
    } catch (e) {
      return e.code === "ESRCH";
    } // Permission failures never steal a live lease.
  }
  function acquire(name, depth = 0) {
    if (depth > policy.max_depth) throw busy();
    const filename = safePath(root, name);
    for (let attempt = 0; attempt < 4; attempt++) {
      const contents = JSON.stringify({
        pid: process.pid,
        created_ms: Date.now(),
        token: randomBytes(16).toString("hex"),
      });
      let fd;
      try {
        fd = fs.openSync(filename, "wx", 0o600);
      } catch (e) {
        if (e.code !== "EEXIST") throw e;
      }
      if (fd !== undefined) {
        const release = () => {
          if (snapshot(filename)?.contents === contents)
            fs.unlinkSync(filename);
        };
        try {
          fs.writeFileSync(fd, contents);
          fs.fsyncSync(fd);
        } catch (e) {
          release();
          throw e;
        } finally {
          fs.closeSync(fd);
        }
        return release;
      }
      const previous = snapshot(filename);
      if (!previous) continue;
      if (!stale(previous)) throw busy();
      const releaseReaper = acquire(
        core.lockRecoveryName(name, previous.contents),
        depth + 1,
      );
      try {
        const current = snapshot(filename);
        if (current?.contents === previous.contents && stale(current))
          fs.unlinkSync(filename);
      } finally {
        releaseReaper();
      }
    }
    throw busy();
  }
  const release = acquire(".lock");
  return async () => release();
}
