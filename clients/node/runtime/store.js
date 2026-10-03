import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { safePath } from "./host.js";
import {
  DataNotInstalledError,
  IncompatibleDataError,
  integrity,
  usage,
  atPack,
} from "./errors.js";
import { wasm } from "./wasm.js";
export const FAMILIES = [
  "core",
  "postal",
  "airports",
  "locode",
  "phone",
  "ip",
  "plates",
];
export const MAX_METADATA = 16 * 1024 * 1024;
export function family(value) {
  if (!FAMILIES.includes(value)) throw usage(`Unknown pack family: ${value}`);
  return value;
}
export function component(value) {
  if (
    typeof value !== "string" ||
    !/^[a-z\d_-][a-z\d._-]{0,127}$/i.test(value) ||
    value.endsWith(".") ||
    /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(value)
  )
    throw integrity("Invalid release directory component");
  return value;
}
export function directory(
  explicit,
  env = process.env,
  platform = process.platform,
) {
  let result = explicit ?? (env.THEREABOUTS_DATA || undefined);
  if (result) {
    if (result === "~" || result.startsWith("~/")) {
      const home = env.HOME || env.USERPROFILE;
      if (!home) throw usage("Cannot expand home directory");
      result = path.join(home, result.slice(2));
    }
    return path.resolve(result);
  }
  if (platform === "win32") {
    if (!env.LOCALAPPDATA) throw usage("Set THEREABOUTS_DATA or LOCALAPPDATA");
    return path.join(env.LOCALAPPDATA, "Thereabouts");
  }
  if (platform !== "darwin" && env.XDG_DATA_HOME)
    return path.join(env.XDG_DATA_HOME, "thereabouts");
  if (!env.HOME) throw usage("Set THEREABOUTS_DATA or HOME");
  return path.join(
    env.HOME,
    platform === "darwin"
      ? "Library/Application Support/Thereabouts"
      : ".local/share/thereabouts",
  );
}
export function readJson(filename) {
  const meta = fs.lstatSync(filename);
  if (!meta.isFile() || meta.size > MAX_METADATA)
    throw integrity(`Invalid metadata file: ${filename}`);
  try {
    return JSON.parse(fs.readFileSync(filename, "utf8"));
  } catch (e) {
    throw integrity(`Invalid JSON in ${filename}: ${e.message}`);
  }
}
export function keys(value, allowed) {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.keys(value).some((k) => !allowed.includes(k))
  )
    throw integrity("Invalid metadata fields");
}
export function sha256(filename) {
  const hash = createHash("sha256"),
    fd = fs.openSync(filename, "r"),
    buffer = Buffer.alloc(65536);
  try {
    for (;;) {
      const n = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (!n) break;
      hash.update(buffer.subarray(0, n));
    }
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest("hex");
}
export function active(root) {
  const filename = safePath(root, "active.json");
  if (!fs.existsSync(filename)) return null;
  const pin = readJson(filename);
  keys(pin, ["data_version", "packs"]);
  component(pin.data_version);
  keys(pin.packs, FAMILIES);
  for (const [name, pointer] of Object.entries(pin.packs)) {
    family(name);
    keys(pointer, ["path", "manifest_sha256"]);
  }
  return pin;
}
export async function resolve(root, name, pointer, version) {
  let filename = root;
  try {
    filename = safePath(root, pointer.path);
    if (sha256(safePath(filename, "manifest.json")) !== pointer.manifest_sha256)
      throw integrity("Active manifest digest mismatch");
    const info = JSON.parse((await wasm()).packInfo(filename, false));
    if (
      info.family !== name ||
      (version !== undefined && version !== info.data_version)
    )
      throw integrity("Active pack identity mismatch");
    const ordinary = `packs/${name}/${info.data_version}`;
    const escaped = encodeURIComponent(info.data_version).replace(
      /[!'()*]/g,
      (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
    );
    const legacy = `packs/${name}/v-${escaped}/${pointer.manifest_sha256}`;
    if (pointer.path !== ordinary && pointer.path !== legacy)
      throw integrity("Active path differs from immutable pack identity");
    return filename;
  } catch (e) {
    throw atPack(e, filename, name);
  }
}
export async function installed(root, name) {
  family(name);
  const pin = active(root);
  if (pin) {
    if (!pin.packs[name]) throw new DataNotInstalledError(name);
    return resolve(root, name, pin.packs[name], pin.data_version);
  }
  const current = safePath(root, `packs/${name}/current.json`);
  if (fs.existsSync(current)) return resolve(root, name, readJson(current));
  if (
    name === "core" &&
    fs.existsSync(safePath(root, "packs/reverse/current.json"))
  )
    throw new IncompatibleDataError(
      "Legacy reverse data requires a format-2 core pack",
    );
  throw new DataNotInstalledError(name);
}
export async function inventory(root, all = false) {
  const result = [],
    selected = new Set();
  for (const name of FAMILIES) {
    try {
      selected.add(await installed(root, name));
    } catch (e) {
      if (!(e instanceof DataNotInstalledError)) throw e;
    }
  }
  const paths = new Set(selected);
  if (all)
    for (const name of FAMILIES) {
      const folder = safePath(root, `packs/${name}`);
      if (!fs.existsSync(folder)) continue;
      for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
        if (entry.isSymbolicLink())
          throw integrity("Symlink installation directory");
        if (entry.isDirectory()) {
          const child = safePath(folder, entry.name);
          if (fs.existsSync(safePath(child, "manifest.json"))) paths.add(child);
          else if (entry.name.startsWith("v-"))
            for (const digest of fs.readdirSync(child)) {
              const legacy = safePath(child, digest);
              if (fs.existsSync(safePath(legacy, "manifest.json")))
                paths.add(legacy);
            }
        }
      }
    }
  const core = await wasm();
  for (const filename of [...paths].sort()) {
    try {
      result.push({
        path: filename,
        active: selected.has(filename),
        info: JSON.parse(core.packInfo(filename, false)),
      });
    } catch (e) {
      throw atPack(
        e,
        filename,
        path.relative(root, filename).split(path.sep)[1] ?? "core",
      );
    }
  }
  return result;
}
export async function activate(root, pin) {
  component(pin.data_version);
  const paths = {};
  for (const [name, pointer] of Object.entries(pin.packs))
    paths[name] = await resolve(root, name, pointer, pin.data_version);
  const module = await wasm();
  const core = paths.core ? module.Geocoder.open(paths.core, false) : null;
  try {
    if (core)
      for (const [name, filename] of Object.entries(paths))
        if (name !== "core") {
          const pack = module.Geocoder.openWithCore(filename, false, core);
          pack.free();
        }
  } finally {
    core?.free();
  }
  const temporary = safePath(root, ".active.json.tmp");
  const fd = fs.openSync(temporary, "w");
  try {
    fs.writeFileSync(fd, JSON.stringify(pin, null, 2));
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(temporary, safePath(root, "active.json"));
}
