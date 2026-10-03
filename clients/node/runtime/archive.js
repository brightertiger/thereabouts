import fs from "node:fs";
import path from "node:path";
import { safePath } from "./host.js";
import { integrity } from "./errors.js";
// Ustar is merely a transport envelope. WASM verifies every extracted pack.
export function extract(filename, output, size) {
  const fd = fs.openSync(filename, "r"),
    buffer = Buffer.alloc(65536);
  let offset = 0,
    zero = false;
  const seen = new Set();
  function read(length) {
    const bytes = Buffer.alloc(length);
    let n = 0;
    while (n < length) {
      const got = fs.readSync(fd, bytes, n, length - n, offset + n);
      if (!got) throw integrity("Truncated archive");
      n += got;
    }
    offset += length;
    if (offset > size) throw integrity("Archive exceeds advertised length");
    return bytes;
  }
  function text(bytes) {
    const n = bytes.indexOf(0);
    return new TextDecoder("utf8", { fatal: true }).decode(
      n < 0 ? bytes : bytes.subarray(0, n),
    );
  }
  function octal(bytes) {
    const value = text(bytes).trim();
    if (!/^[0-7]+$/.test(value)) throw integrity("Invalid tar numeric field");
    const n = parseInt(value, 8);
    if (!Number.isSafeInteger(n)) throw integrity("Tar length overflow");
    return n;
  }
  try {
    for (;;) {
      const header = read(512);
      if (header.every((b) => b === 0)) {
        if (zero) break;
        zero = true;
        continue;
      }
      if (zero) throw integrity("Invalid archive terminator");
      const sum = header.reduce(
        (a, b, i) => a + (i >= 148 && i < 156 ? 32 : b),
        0,
      );
      if (
        sum !== octal(header.subarray(148, 156)) ||
        !header.subarray(257, 263).equals(Buffer.from("ustar\0"))
      )
        throw integrity("Requires POSIX ustar archive");
      const prefix = text(header.subarray(345, 500));
      const relative =
        (prefix ? prefix + "/" : "") + text(header.subarray(0, 100));
      const name = relative.replace(/\/+$/, ""),
        destination = safePath(output, name);
      if (name === ".archive.json" || seen.has(name))
        throw integrity("Duplicate or reserved archive path");
      seen.add(name);
      const length = octal(header.subarray(124, 136)),
        padding = (512 - (length % 512)) % 512;
      if (offset + length + padding > size)
        throw integrity("Archive entry exceeds length");
      const kind = header[156];
      if (kind === 53 && length === 0)
        fs.mkdirSync(destination, { recursive: true });
      else if (kind === 0 || kind === 48) {
        fs.mkdirSync(path.dirname(destination), { recursive: true });
        const out = fs.openSync(destination, "wx");
        try {
          let left = length;
          while (left) {
            const n = Math.min(left, buffer.length),
              bytes = read(n);
            let written = 0;
            while (written < n)
              written += fs.writeSync(out, bytes, written, n - written);
            left -= n;
          }
          fs.fsyncSync(out);
        } finally {
          fs.closeSync(out);
        }
        read(padding);
      } else throw integrity("Archive links and special entries are forbidden");
    }
    while (offset < size)
      if (read(Math.min(size - offset, buffer.length)).some((b) => b !== 0))
        throw integrity("Nonzero archive trailer");
  } finally {
    fs.closeSync(fd);
  }
}
