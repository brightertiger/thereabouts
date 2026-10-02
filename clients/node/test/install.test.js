import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { mkdtemp, mkdir, rm, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  importPack,
  verifyPack,
  Geocoder,
  CorruptPackError,
  DataNotInstalledError,
} from "../src/index.js";
import { sha256 } from "../src/json.js";

const fixtures = fileURLToPath(
  new URL("../../../tests/fixtures/", import.meta.url),
);
const scratch = fileURLToPath(
  new URL("../../../.cache/node-tests/", import.meta.url),
);
await mkdir(scratch, { recursive: true });
test("pinned standalone import, simultaneous publication and offline discovery", async () => {
  const dataDir = await mkdtemp(join(scratch, "store-"));
  const source = join(fixtures, "codes/postal");
  const manifestSha256 = sha256(await readFile(join(source, "manifest.json")));
  try {
    await assert.rejects(Geocoder.open({ dataDir }), DataNotInstalledError);
    await assert.rejects(
      importPack(source, { dataDir, manifestSha256: "0".repeat(64) }),
      CorruptPackError,
    );
    const paths = await Promise.all([
      importPack(source, { dataDir, manifestSha256 }),
      importPack(source, { dataDir, manifestSha256 }),
    ]);
    assert.equal(paths[0], paths[1]);
    assert.equal((await verifyPack(paths[0])).manifest_sha256, manifestSha256);
    const reader = await Geocoder.open({ dataDir, packs: ["postal"] });
    try {
      assert.equal(
        (await reader.postal("AMB", { country: "AA" })).status,
        "ambiguous",
      );
    } finally {
      await reader.close();
    }
    const pointer = join(dataDir, "packs/postal/current.json");
    const value = JSON.parse(await readFile(pointer));
    value.manifest_sha256 = "f".repeat(64);
    await writeFile(pointer, JSON.stringify(value));
    await assert.rejects(
      Geocoder.open({ dataDir, packs: ["postal"] }),
      CorruptPackError,
    );
  } finally {
    await rm(dataDir, { recursive: true, force: true });
  }
});

test("publication refuses a symlink inside the installation tree", async () => {
  const { symlink } = await import("node:fs/promises");
  const root = await mkdtemp(join(scratch, "unsafe-store-"));
  const source = join(fixtures, "codes/postal");
  const manifestSha256 = sha256(await readFile(join(source, "manifest.json")));
  try {
    const dataDir = join(root, "store");
    await mkdir(dataDir);
    await mkdir(join(root, "elsewhere"));
    await symlink(join(root, "elsewhere"), join(dataDir, "packs"));
    await assert.rejects(
      importPack(source, { dataDir, manifestSha256 }),
      CorruptPackError,
    );
    const { readdir } = await import("node:fs/promises");
    assert.deepEqual(await readdir(join(root, "elsewhere")), []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
