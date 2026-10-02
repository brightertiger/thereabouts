import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cp,
  readFile,
  writeFile,
  mkdtemp,
  rm,
  mkdir,
  symlink,
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { verifyPack, CorruptPackError } from "../src/index.js";
import { sha256, parse, canonical } from "../src/json.js";

const fixtures = fileURLToPath(
  new URL("../../../tests/fixtures/", import.meta.url),
);
const scratch = fileURLToPath(
  new URL("../../../.cache/node-tests/", import.meta.url),
);
await mkdir(scratch, { recursive: true });
const bundle = JSON.parse(
  await readFile(join(fixtures, "malformed.json"), "utf8"),
);
for (const item of bundle.cases) {
  test(`malformed: ${item.id}`, async () => {
    const root = await mkdtemp(join(scratch, "bad-"));
    try {
      await cp(join(fixtures, item.pack), root, { recursive: true });
      const path = join(root, "manifest.json");
      const manifest = JSON.parse(await readFile(path, "utf8"));
      if (item.manifest) {
        let parent = manifest;
        for (const part of item.manifest.slice(0, -1)) parent = parent[part];
        parent[item.manifest.at(-1)] = item.value;
      } else if (item.kind) {
        const record = manifest.files.find((f) => f.kind === item.kind);
        const file = join(root, record.path);
        const bytes = await readFile(file);
        Buffer.from(item.hex, "hex").copy(bytes, item.offset);
        await writeFile(file, bytes);
        if (item.rehash) record.sha256 = sha256(bytes);
      }
      let serialized = JSON.stringify(manifest);
      if (item.duplicate)
        serialized = '{"schema":"duplicate",' + serialized.slice(1);
      await writeFile(path, serialized);
      await assert.rejects(verifyPack(root), { name: item.error });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
}
test("JSON duplicate, nonfinite, unsafe integer and Unicode checks", () => {
  for (const value of [
    '{"a":1,"a":2}',
    "1e999",
    "9007199254740993",
    '"\\ud800"',
    "\ufeff{}",
    '{"x":1,}',
  ]) {
    assert.throws(() => parse(Buffer.from(value)), CorruptPackError);
  }
  assert.deepEqual(
    parse(Buffer.from('{"__proto__":{"x":1}}')),
    JSON.parse('{"__proto__":{"x":1}}'),
  );
  assert.equal(canonical({ "𐀀": 1, "\ue000": 2 }), '{"":2,"𐀀":1}');
});
test("symlink artifacts are rejected", async () => {
  const root = await mkdtemp(join(scratch, "link-"));
  try {
    await cp(join(fixtures, "serving"), root, { recursive: true });
    const manifest = JSON.parse(await readFile(join(root, "manifest.json")));
    const record = manifest.files[0];
    await rm(join(root, record.path));
    await symlink(
      join(fixtures, "serving", record.path),
      join(root, record.path),
    );
    await assert.rejects(verifyPack(root), CorruptPackError);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("zlib payloads reject trailing streams despite recomputed file hashes", async () => {
  for (const trailer of [
    Buffer.from("trailing"),
    Buffer.from("789c030000000001", "hex"),
  ]) {
    const root = await mkdtemp(join(scratch, "trailer-"));
    try {
      await cp(join(fixtures, "codes/postal"), root, { recursive: true });
      const manifestPath = join(root, "manifest.json");
      const manifest = JSON.parse(await readFile(manifestPath));
      const record = manifest.files.find((file) => file.kind === "exact");
      const file = join(root, record.path);
      const original = await readFile(file);
      const bytes = Buffer.concat([original, trailer]);
      bytes.writeBigUInt64LE(BigInt(bytes.length), 24);
      const records = Number(bytes.readBigUInt64LE(56));
      const last = Number(bytes.readBigUInt64LE(40)) + (records - 1) * 40;
      bytes.writeBigUInt64LE(
        bytes.readBigUInt64LE(last + 24) + BigInt(trailer.length),
        last + 24,
      );
      for (const field of [112, 120])
        bytes.writeBigUInt64LE(
          bytes.readBigUInt64LE(field) + BigInt(trailer.length),
          field,
        );
      await writeFile(file, bytes);
      record.size = bytes.length;
      record.sha256 = sha256(bytes);
      await writeFile(manifestPath, JSON.stringify(manifest));
      await assert.rejects(verifyPack(root), /trailing stream/);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  }
});
