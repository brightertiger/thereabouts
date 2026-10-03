import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { readFile } from "node:fs/promises";
import { artifact, relative } from "./files.js";
import { parse } from "./json.js";
import { check, InvalidInputError, DataNotInstalledError } from "./errors.js";
import { readManifest } from "./manifest.js";

export function dataDirectory(explicit) {
  const selected = explicit ?? process.env.THEREABOUTS_DATA;
  if (selected)
    return resolve(
      selected === "~"
        ? homedir()
        : selected.startsWith("~/")
          ? join(homedir(), selected.slice(2))
          : selected,
    );
  if (process.platform === "darwin")
    return join(homedir(), "Library/Application Support/Thereabouts");
  if (process.platform === "win32") {
    if (!process.env.LOCALAPPDATA)
      throw new DataNotInstalledError("Set THEREABOUTS_DATA or LOCALAPPDATA");
    return join(process.env.LOCALAPPDATA, "Thereabouts");
  }
  return join(
    process.env.XDG_DATA_HOME ?? join(homedir(), ".local/share"),
    "thereabouts",
  );
}
export function installationName(manifest) {
  const version = encodeURIComponent(manifest.data_version).replace(
    /[!'()*]/g,
    (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
  );
  return `packs/${manifest.family}/v-${version}/${manifest.manifest_sha256}`;
}
export async function installedPack(dataDir, family = "reverse") {
  if (!["reverse", "postal", "airports"].includes(family))
    throw new InvalidInputError("Unsupported pack family");
  const root = dataDirectory(dataDir);
  let path;
  try {
    path = await artifact(root, `packs/${family}/current.json`);
  } catch (error) {
    if (error.code === "ENOENT")
      throw new DataNotInstalledError(
        `No ${family} pack installed; install data explicitly`,
      );
    throw error;
  }
  const pointer = parse(await readFile(path));
  const name = relative(pointer.path);
  await artifact(root, `${name}/manifest.json`);
  const manifest = await readManifest(join(root, name));
  check(
    manifest.manifest_sha256 === pointer.manifest_sha256 &&
      manifest.family === family &&
      name === installationName(manifest),
    "Invalid active pack identity",
  );
  return join(root, name);
}
