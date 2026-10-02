import {
  copyFile,
  mkdir,
  mkdtemp,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";
import { artifact, directory, manifestBytes } from "./files.js";
import { Pack } from "./pack.js";
import { check, InvalidInputError } from "./errors.js";
import { sha256 } from "./json.js";
import { dataDirectory, installationName } from "./store.js";

export async function verifyPack(path) {
  const pack = await Pack.open(path, 32 * 1024 * 1024, true);
  const manifest = structuredClone(pack.manifest);
  pack.close();
  return manifest;
}
export async function importPack(source, { dataDir, manifestSha256 } = {}) {
  if (
    typeof manifestSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifestSha256)
  )
    throw new InvalidInputError("A trusted manifestSha256 is required");
  const bytes = await manifestBytes(source);
  check(sha256(bytes) === manifestSha256, "Manifest pin mismatch");
  const manifest = await verifyPack(source);
  check(
    manifest.manifest_sha256 === manifestSha256,
    "Source changed during verification",
  );
  const root = dataDirectory(dataDir);
  await mkdir(root, { recursive: true });
  const staging = await mkdtemp(join(root, ".import-"));
  try {
    for (const record of manifest.files) {
      const from = await artifact(source, record.path, record.size);
      const destination = join(staging, record.path);
      await mkdir(dirname(destination), { recursive: true });
      await copyFile(from, destination);
    }
    await writeFile(join(staging, "manifest.json"), bytes, { flag: "wx" });
    await verifyPack(staging);
    const name = installationName(manifest),
      destination = join(root, name);
    await directory(root, name.split("/").slice(0, -1).join("/"));
    try {
      await rename(staging, destination);
    } catch (error) {
      if (!["EEXIST", "ENOTEMPTY"].includes(error.code)) throw error;
      await artifact(root, `${name}/manifest.json`);
      const existing = await verifyPack(destination);
      check(
        existing.manifest_sha256 === manifestSha256,
        "Existing installation identity mismatch",
      );
    }
    const pointer = join(root, `packs/${manifest.family}/current.json`);
    const temporary = `${pointer}.${randomUUID()}.tmp`;
    try {
      await writeFile(
        temporary,
        JSON.stringify({ path: name, manifest_sha256: manifestSha256 }) + "\n",
        { flag: "wx" },
      );
      await rename(temporary, pointer);
    } finally {
      await rm(temporary, { force: true });
    }
    return destination;
  } finally {
    await rm(staging, { recursive: true, force: true });
  }
}
