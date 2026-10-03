import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { temporary, fixtureStore, selection, console, BIN } from "./helpers.js";

test(
  "batch accepts FIFOs and process substitution as sequential user streams",
  { skip: process.platform === "win32" },
  (t) => {
    const root = temporary(t);
    fixtureStore(root, selection("packs/core-sample"));
    const fifo = path.join(root, "points.csv");
    assert.equal(spawnSync("mkfifo", [fifo]).status, 0);
    const writer = spawn(
      process.execPath,
      [
        "-e",
        'require("fs").writeFileSync(process.argv[1], "lat,lon\\n48.8566,2.3522\\n")',
        fifo,
      ],
      { env: process.env },
    );
    t.after(() => writer.kill());
    const piped = console(root, ["reverse", fifo]);
    assert.equal(piped.status, 0, piped.stderr);
    assert.equal(JSON.parse(piped.stdout).thereabouts_status, "matched");
    const substituted = spawnSync(
      "bash",
      [
        "-c",
        '"$1" --import "$2" "$3" --data-dir "$4" reverse <(printf "lat,lon\\n48.8566,2.3522\\n")',
        "--",
        process.execPath,
        new URL("./offline.js", import.meta.url).pathname,
        BIN,
        root,
      ],
      { encoding: "utf8", env: process.env, timeout: 20_000 },
    );
    assert.equal(substituted.status, 0, substituted.stderr);
    assert.equal(JSON.parse(substituted.stdout).thereabouts_status, "matched");
  },
);
