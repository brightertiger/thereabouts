import { lstat, mkdir, open, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { check, integer, string } from "./errors.js";

export const PAGE_BYTES = 64 * 1024;
export function relative(name) {
  string(name);
  check(!name.includes("\\") && !name.includes(":"), "Unsafe artifact path");
  check(
    name.split("/").every((part) => part && part !== "." && part !== ".."),
    "Unsafe artifact path",
  );
  return name;
}
export async function artifact(root, name, size) {
  let path = resolve(root);
  const parts = relative(name).split("/");
  for (let i = 0; i < parts.length; i++) {
    path = join(path, parts[i]);
    const stat = await lstat(path);
    check(!stat.isSymbolicLink(), "Symlink artifact");
    check(
      i + 1 === parts.length ? stat.isFile() : stat.isDirectory(),
      "Invalid artifact type",
    );
    if (i + 1 === parts.length && size !== undefined)
      check(stat.size === size, "Artifact size mismatch");
  }
  return path;
}
export async function digestFile(path) {
  const handle = await open(path, "r");
  const hash = createHash("sha256");
  try {
    const buffer = Buffer.allocUnsafe(PAGE_BYTES);
    let offset = 0;
    while (true) {
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, offset);
      if (!bytesRead) break;
      offset += bytesRead;
      hash.update(buffer.subarray(0, bytesRead));
    }
    return hash.digest("hex");
  } finally {
    await handle.close();
  }
}
export async function manifestBytes(root) {
  return readFile(await artifact(root, "manifest.json"));
}
export class File {
  constructor(path, size, cache) {
    this.path = path;
    this.size = size;
    this.cache = cache;
  }
  async page(number) {
    const key = `${this.path}:${number}`;
    const cached = this.cache.get(key);
    if (cached) return cached;
    const offset = number * PAGE_BYTES;
    const bytes = Buffer.allocUnsafe(Math.min(PAGE_BYTES, this.size - offset));
    const handle = await open(this.path, "r");
    try {
      let done = 0;
      while (done < bytes.length) {
        const { bytesRead } = await handle.read(
          bytes,
          done,
          bytes.length - done,
          offset + done,
        );
        check(bytesRead > 0, "Truncated artifact");
        done += bytesRead;
      }
    } finally {
      await handle.close();
    }
    return this.cache.put(key, bytes);
  }
  async read(offset, length) {
    integer(offset);
    integer(length);
    check(
      Number.isSafeInteger(offset + length) && offset + length <= this.size,
      "Read outside artifact",
    );
    const result = Buffer.allocUnsafe(length);
    let done = 0;
    while (done < length) {
      const position = offset + done;
      const page = await this.page(Math.floor(position / PAGE_BYTES));
      const local = position % PAGE_BYTES;
      const count = Math.min(page.length - local, length - done);
      page.copy(result, done, local, local + count);
      done += count;
    }
    return result;
  }
}

export async function directory(root, name) {
  let path = resolve(root);
  for (const part of relative(name).split("/")) {
    path = join(path, part);
    await mkdir(path, { recursive: true });
    const stat = await lstat(path);
    check(
      stat.isDirectory() && !stat.isSymbolicLink(),
      "Unsafe installation directory",
    );
  }
  return path;
}
