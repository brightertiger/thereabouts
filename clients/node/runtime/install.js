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
import {
  index,
  select,
  selectDataset,
  archive,
  DATASET_MANIFEST_FORMAT,
} from "./transport.js";
import { convert, integrity, usage, DataNotInstalledError } from "./errors.js";
import { wasm } from "./wasm.js";
export const DISK_MARGIN_BYTES = 64 * 1024 * 1024;
// Every compressed download plus its expanded tar stream, which bounds the files.
export function precheck(root, bytes) {
  const stat = fs.statfsSync(root),
    available = stat.bavail * stat.bsize,
    needed = bytes + DISK_MARGIN_BYTES;
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
  return info;
}
// The shared Rust reader refuses unsafe entries and stops at the declared size.
async function extract(filename, staging, pack) {
  let summary;
  try {
    summary = JSON.parse(
      (await wasm()).extractArchive(filename, staging, pack.unpacked_size),
    );
  } catch (e) {
    throw e.code === "cli_error" ? e : convert(e);
  }
  return summary.files.map((f) => f.path).sort();
}
// Download (or resume) one release file ({url, api_url?, size, sha256}).
async function download(root, origin, pack) {
  const filename = safePath(root, `.downloads/${pack.sha256}.part`);
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const fd = fs.openSync(filename, "a");
  let offset = fs.fstatSync(fd).size;
  try {
    if (offset > pack.size) {
      fs.unlinkSync(filename);
      throw integrity("Partial download exceeds advertised size");
    }
    if (offset < pack.size)
      for await (const bytes of archive(origin, pack, offset)) {
        if (offset + bytes.length > pack.size)
          throw integrity("Download exceeds advertised size");
        let written = 0;
        while (written < bytes.length)
          written += fs.writeSync(fd, bytes, written, bytes.length - written);
        offset += bytes.length;
      }
    fs.fsyncSync(fd);
    if (offset !== pack.size)
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
    if (receipt.sha256 !== pack.sha256 || receipt.size !== pack.size)
      throw integrity("Installed release archive identity changed");
    return pointer(root, destination);
  }
  const filename = await download(root, origin, pack),
    staging = safePath(root, `.staging/${pack.sha256}`);
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(staging, { recursive: true });
  try {
    const files = await extract(filename, staging, pack),
      info = await identity(staging, version, name, pack),
      expected = ["manifest.json", ...info.files.map((f) => f.path)].sort();
    if (files.join("\n") !== expected.join("\n"))
      throw integrity("Archive files differ from the pack manifest");
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
        const quote = (value) =>
          `'${String(value).replaceAll("'", "'\"'\"'")}'`;
        const location = ` --from ${quote(origin)} --data-dir ${quote(root)}`;
        throw usage(
          `Changing dataset version requires every active family. Run:\nthereabouts data install ${all.join(" ")} --version ${selected}${location}\nTo keep the active version:\nthereabouts data install ${requested.join(" ")} --version ${pin.data_version}${location}`,
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
      requested.reduce(
        (sum, name) =>
          sum + dataset.packs[name].size + dataset.packs[name].unpacked_size,
        0,
      ),
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
function datasetFiles(listed, version) {
  if (
    !listed ||
    listed.format !== DATASET_MANIFEST_FORMAT ||
    listed.version !== version ||
    !Array.isArray(listed.archives) ||
    !Array.isArray(listed.files)
  )
    throw integrity("Dataset manifest differs from the release index");
  const expected = new Map(),
    names = new Set();
  const add = (member, nested) => {
    if (
      typeof member?.path !== "string" ||
      member.path.includes("/") !== nested ||
      !Number.isSafeInteger(member.size) ||
      member.size < 0 ||
      !/^[a-f\d]{64}$/.test(member.sha256) ||
      expected.has(member.path)
    )
      throw integrity("Invalid dataset manifest entry");
    if (
      member.path
        .split("/")
        .some((part) => !part || part === "." || part === "..") ||
      /[\\:]/.test(member.path)
    )
      throw integrity("Unsafe dataset path");
    expected.set(member.path, member);
  };
  for (const item of listed.archives) {
    if (
      typeof item?.name !== "string" ||
      names.has(item.name) ||
      !Array.isArray(item.files) ||
      !item.files.length ||
      item.files.reduce((sum, f) => sum + f.size, 0) !== item.unpacked_size ||
      !Number.isSafeInteger(item.size) ||
      !/^[a-f\d]{64}$/.test(item.sha256)
    )
      throw integrity("Invalid dataset archive identity");
    names.add(item.name);
    for (const member of item.files) add(member, true);
  }
  for (const document of listed.files) add(document, false);
  return expected;
}
function listing(root, relative = "", found = new Map()) {
  for (const entry of fs.readdirSync(path.join(root, relative), {
    withFileTypes: true,
  })) {
    const name = relative ? `${relative}/${entry.name}` : entry.name;
    if (entry.isDirectory()) listing(root, name, found);
    else if (entry.isFile()) found.set(name, path.join(root, name));
    else throw integrity("Dataset holds a link or special file");
  }
  return found;
}
// The tree holds exactly the promised files with their sizes and digests.
function verifyTree(root, expected) {
  const found = listing(root);
  if (
    [...found.keys()].sort().join("\n") !==
    [...expected.keys()].sort().join("\n")
  )
    throw integrity("Dataset files differ from the dataset manifest");
  for (const [name, filename] of found) {
    const member = expected.get(name);
    if (
      fs.statSync(filename).size !== member.size ||
      sha256(filename) !== member.sha256
    )
      throw integrity(
        `Dataset file differs from the dataset manifest: ${name}`,
      );
  }
}
const key = (f) => `${f.path}\0${f.size}\0${f.sha256}`;
// Restore dataset/<version>/ from the release's table zips, all or nothing.
export async function installDataset(root, origin, version) {
  const [selected, file] = selectDataset(await index(origin), version),
    release = await lock(root);
  try {
    const described = await download(root, origin, file),
      listed = readJson(described),
      expected = datasetFiles(listed, selected),
      destination = safePath(root, `dataset/${selected}`);
    const summary = (installed) => ({
      dataset: {
        version: selected,
        path: destination,
        files: expected.size,
        bytes: [...expected.values()].reduce((sum, m) => sum + m.size, 0),
        installed,
      },
    });
    if (fs.existsSync(destination)) {
      verifyTree(destination, expected);
      fs.rmSync(described, { force: true });
      return summary(false);
    }
    precheck(
      root,
      listed.archives.reduce((s, a) => s + a.size + a.unpacked_size, 0) +
        listed.files.reduce((s, d) => s + d.size, 0),
    );
    const staging = safePath(root, `.staging/dataset-${selected}`),
      fetched = [described];
    fs.rmSync(staging, { recursive: true, force: true });
    fs.mkdirSync(staging, { recursive: true });
    try {
      for (const item of listed.archives) {
        const filename = await download(root, origin, item);
        fetched.push(filename);
        let extracted;
        try {
          extracted = JSON.parse(
            (await wasm()).extractZip(filename, staging, item.unpacked_size),
          );
        } catch (e) {
          throw e.code === "cli_error" ? e : convert(e);
        }
        if (
          extracted.files.map(key).sort().join("\n") !==
          item.files.map(key).sort().join("\n")
        )
          throw integrity(
            `Dataset archive differs from the dataset manifest: ${item.name}`,
          );
      }
      for (const document of listed.files) {
        const filename = await download(root, origin, document);
        fetched.push(filename);
        const target = safePath(staging, document.path);
        if (fs.existsSync(target)) throw integrity("Duplicate dataset file");
        fs.copyFileSync(filename, target);
      }
      verifyTree(staging, expected);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.renameSync(staging, destination);
    } finally {
      fs.rmSync(staging, { recursive: true, force: true });
    }
    for (const filename of fetched) fs.rmSync(filename, { force: true });
    return summary(true);
  } finally {
    await release();
  }
}
