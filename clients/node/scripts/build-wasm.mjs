import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../../..", import.meta.url));
const out = path.join(root, "clients/node/pkg");
const target = path.join(root, "core/target");
mkdirSync(out, { recursive: true });
function run(executable, args) {
  const result = spawnSync(executable, args, {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, CARGO_TARGET_DIR: target },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
run("cargo", [
  "build",
  "--locked",
  "--manifest-path",
  "core/Cargo.toml",
  "-p",
  "thereabouts-wasm",
  "--target",
  "wasm32-unknown-unknown",
  "--release",
]);
run(process.env.WASM_BINDGEN ?? "wasm-bindgen", [
  "--target",
  "web",
  "--out-dir",
  out,
  "--out-name",
  "thereabouts",
  path.join(target, "wasm32-unknown-unknown/release/thereabouts_wasm.wasm"),
]);
