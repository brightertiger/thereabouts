import fs from "node:fs";
import path from "node:path";
import { lock } from "./lease.js";
export { lock } from "./lease.js";
import { safePath } from "./host.js";
import {
  active,
  activate,
  family,
  FAMILIES,
  installed,
  readJson,
  sha256,
} from "./store.js";
import { index, select, archive } from "./transport.js";
import { integrity, usage, DataNotInstalledError } from "./errors.js";
import { wasm } from "./wasm.js";
import { extract } from "./archive.js";
export const DISK_MARGIN_BYTES = 64 * 1024 * 1024;
export function precheck(root, bytes) {
  const stat = fs.statfsSync(root),
    available = stat.bavail * stat.bsize,
    needed = bytes * 2 + DISK_MARGIN_BYTES;
  if (!Number.isSafeInteger(needed) || available < needed)
    throw usage(
      `Not enough disk space: need ${needed} bytes, available ${available} bytes`,
    );
}
function pointer(root, filename) {
  return {
    path: path.relative(root, filename).split(path.sep).join("/"),
    manifest_sha256: sha256(safePath(filename, "manifest.json")),
  };
}
async function identity(filename, version, name, pack) {
  const info = JSON.parse((await wasm()).packInfo(filename, true));
  if (
    info.data_version !== version ||
    info.family !== name ||
    info.format_minor !== pack.format_minor
  )
    throw integrity("Downloaded pack differs from release index identity");
}
async function download(root, origin, pack) {
  const filename = safePath(root, `.downloads/${pack.sha256}.part`);
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const fd = fs.openSync(filename, "a");
  let offset = fs.fstatSync(fd).size;
  try {
    if (offset > pack.bytes) {
      fs.unlinkSync(filename);
      throw integrity("Partial download exceeds advertised size");
    }
    if (offset < pack.bytes)
      for await (const bytes of archive(origin, pack, offset)) {
        if (offset + bytes.length > pack.bytes)
          throw integrity("Download exceeds advertised size");
        let written = 0;
        while (written < bytes.length)
          written += fs.writeSync(fd, bytes, written, bytes.length - written);
        offset += bytes.length;
      }
    fs.fsyncSync(fd);
    if (offset !== pack.bytes)
      throw usage(
        "Download interrupted; run the same data install again to resume: incomplete response",
      );
  } finally {
    fs.closeSync(fd);
  }
  if (sha256(filename) !== pack.sha256) {
    fs.unlinkSync(filename);
    throw integrity("Downloaded archive checksum mismatch");
  }
  return filename;
}
async function one(root, origin, version, name, pack) {
  const destination = safePath(root, `packs/${name}/${version}`);
  if (fs.existsSync(destination)) {
    await identity(destination, version, name, pack);
    const receipt = readJson(safePath(destination, ".archive.json"));
    if (receipt.sha256 !== pack.sha256 || receipt.bytes !== pack.bytes)
      throw integrity("Installed release archive identity changed");
    return pointer(root, destination);
  }
  const filename = await download(root, origin, pack),
    staging = safePath(root, `.staging/${pack.sha256}`);
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(staging, { recursive: true });
  try {
    extract(filename, staging, pack.bytes);
    await identity(staging, version, name, pack);
    fs.writeFileSync(safePath(staging, ".archive.json"), JSON.stringify(pack), {
      flag: "wx",
    });
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.renameSync(staging, destination);
    fs.unlinkSync(filename);
    return pointer(root, destination);
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
}
export async function install(root, origin, requested, version) {
  if (!requested.length) throw usage("Name at least one pack to install");
  const [selected, dataset] = select(await index(origin), requested, version),
    release = await lock(root);
  try {
    let pin = active(root);
    if (pin && pin.data_version !== selected) {
      if (Object.keys(pin.packs).some((f) => !requested.includes(f))) {
        const all = FAMILIES.filter(
          (f) => pin.packs[f] || requested.includes(f),
        );
        throw usage(
          `Changing dataset version requires every active family. Run:\nthereabouts data install ${all.join(" ")} --version ${selected}`,
        );
      }
      pin = null;
    }
    if (!pin) {
      pin = { data_version: selected, packs: {} };
      for (const name of FAMILIES)
        if (!requested.includes(name)) {
          try {
            const filename = await installed(root, name),
              info = JSON.parse((await wasm()).packInfo(filename, false));
            if (info.data_version === selected)
              pin.packs[name] = pointer(root, filename);
          } catch (e) {
            if (!(e instanceof DataNotInstalledError)) throw e;
          }
        }
    }
    precheck(
      root,
      requested.reduce((sum, name) => sum + dataset.packs[name].bytes, 0),
    );
    for (const name of requested)
      pin.packs[name] = await one(
        root,
        origin,
        selected,
        name,
        dataset.packs[name],
      );
    await activate(root, pin);
    return pin;
  } finally {
    await release();
  }
}
export async function remove(root, name) {
  family(name);
  const release = await lock(root);
  try {
    const pin = active(root);
    if (pin) {
      delete pin.packs[name];
      await activate(root, pin);
    }
    fs.rmSync(safePath(root, `packs/${name}`), {
      recursive: true,
      force: true,
    });
  } finally {
    await release();
  }
}
