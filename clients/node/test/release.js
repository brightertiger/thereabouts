import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { FIXTURES, json } from "./helpers.js";
export function tar(entries) {
  const chunks = [];
  for (const [name, bytes, kind = "0"] of entries) {
    const header = Buffer.alloc(512);
    header.write(name, 0, 100);
    header.write("0000644\0", 100);
    header.write("0000000\0", 108);
    header.write("0000000\0", 116);
    header.write(bytes.length.toString(8).padStart(11, "0") + "\0", 124);
    header.write("00000000000\0", 136);
    header.fill(32, 148, 156);
    header.write(kind, 156);
    header.write("ustar\0", 257);
    header.write("00", 263);
    header.write(
      header
        .reduce((a, b) => a + b, 0)
        .toString(8)
        .padStart(6, "0") + "\0 ",
      148,
    );
    chunks.push(
      header,
      bytes,
      Buffer.alloc((512 - (bytes.length % 512)) % 512),
    );
  }
  return Buffer.concat([...chunks, Buffer.alloc(1024)]);
}
// A valid zstd frame of raw blocks: no compressor dependency in the Node tests.
// Window 128 KiB, no checksum; the shared reader accepts any conforming frame.
export function zstd(bytes, blocks = []) {
  const parts = [Buffer.from([0x28, 0xb5, 0x2f, 0xfd, 0x00, 0x38])];
  const block = (type, size, body, last) => {
    const header = (size << 3) | (type << 1) | (last ? 1 : 0);
    parts.push(
      Buffer.from([header & 255, (header >> 8) & 255, header >> 16]),
      body,
    );
  };
  for (let offset = 0; offset < bytes.length || offset === 0; ) {
    const chunk = bytes.subarray(offset, offset + 131072);
    offset += 131072;
    block(0, chunk.length, chunk, !blocks.length && offset >= bytes.length);
    if (offset >= bytes.length) break;
  }
  // Run-length blocks: four bytes expand to 128 KiB, the shape of a bomb.
  for (const [i, [byte, count]] of blocks.entries())
    for (let left = count; left > 0; left -= 131072)
      block(
        1,
        Math.min(left, 131072),
        Buffer.from([byte]),
        i === blocks.length - 1 && left <= 131072,
      );
  return Buffer.concat(parts);
}
export function publish(root, family, plain, version, extra = {}) {
  const bytes = zstd(plain);
  fs.writeFileSync(path.join(root, `${family}.tar.zst`), bytes);
  const pack = {
    url: `${family}.tar.zst`,
    size: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    unpacked_size: plain.length,
    format_minor: 2,
    ...extra,
  };
  const index = {
    format: 3,
    datasets: { [version]: { packs: { [family]: pack } } },
  };
  fs.writeFileSync(path.join(root, "index.json"), JSON.stringify(index));
  return { index, pack, bytes };
}
export function release(root, family = "phone") {
  fs.mkdirSync(root, { recursive: true });
  const source = path.join(FIXTURES, `packs/${family}-sample`),
    manifest = json(path.join(source, "manifest.json"));
  const plain = tar(
    ["manifest.json", ...manifest.files.map((f) => f.path)].map((name) => [
      name,
      fs.readFileSync(path.join(source, name)),
    ]),
  );
  const published = publish(root, family, plain, manifest.data_version);
  return { ...published, plain, version: manifest.data_version };
}
