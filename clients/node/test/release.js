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
export function release(root, family = "phone") {
  fs.mkdirSync(root, { recursive: true });
  const source = path.join(FIXTURES, `packs/${family}-sample`),
    manifest = json(path.join(source, "manifest.json"));
  const bytes = tar(
    ["manifest.json", ...manifest.files.map((f) => f.path)].map((name) => [
      name,
      fs.readFileSync(path.join(source, name)),
    ]),
  );
  fs.writeFileSync(path.join(root, `${family}.tar`), bytes);
  const pack = {
    url: `${family}.tar`,
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    format_minor: 2,
  };
  const index = {
    format: 2,
    datasets: { [manifest.data_version]: { packs: { [family]: pack } } },
  };
  fs.writeFileSync(path.join(root, "index.json"), JSON.stringify(index));
  return { index, pack, bytes, version: manifest.data_version };
}
