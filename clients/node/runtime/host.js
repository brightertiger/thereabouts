// Host IO only. Pack parsing, indexing and rendering live in WASM.
import fs from "node:fs";
import { lineReader } from "./input.js";
import { writeAll } from "./output.js";
import os from "node:os";
import path from "node:path";
const handles = new Map();
let sequence = 0;
let output = {
  stdout: (s) => writeAll(1, s),
  stderr: (s) => writeAll(2, s),
};
const stdinLine = lineReader(0);
export function safePath(root, relative) {
  if (
    !relative ||
    relative.includes("\\") ||
    relative.includes(":") ||
    relative.startsWith("/") ||
    relative.split("/").some((p) => !p || p === "." || p === "..")
  )
    throw new Error("Unsafe pack path");
  let result = root;
  for (const part of relative.split("/")) {
    result = path.join(result, part);
    try {
      if (fs.lstatSync(result).isSymbolicLink())
        throw new Error(`Symlink path: ${result}`);
    } catch (e) {
      if (e.code !== "ENOENT") throw e;
    }
  }
  return result;
}
// The explicit pack root is trusted, like the native reader's root argument.
// Artifact paths below it still reject symlinks and traversal.
export function canonicalRoot(filename) {
  return fs.realpathSync(filename);
}
export function openHandle(filename) {
  const full = path.resolve(filename);
  safePath(
    path.parse(full).root,
    full.slice(path.parse(full).root.length).split(path.sep).join("/"),
  );
  const fd = fs.openSync(
    full,
    fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0),
  );
  try {
    if (!fs.fstatSync(fd).isFile())
      throw new Error("Pack artifact must be a regular file");
    const id = ++sequence;
    handles.set(id, { fd });
    return id;
  } catch (e) {
    fs.closeSync(fd);
    throw e;
  }
}
// Release extraction: the shared WASM reader validates entry names; the host
// still refuses symlinked or traversing paths and never replaces a file.
export function createDirectory(root, relative) {
  fs.mkdirSync(safePath(root, relative), { recursive: true });
}
export function createFile(root, relative) {
  const filename = safePath(root, relative);
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const fd = fs.openSync(filename, "wx");
  const id = ++sequence;
  handles.set(id, { fd });
  return id;
}
export function syncHandle(id) {
  fs.fsyncSync(get(id).fd);
}
function get(id) {
  const file = handles.get(id);
  if (!file) throw new Error("Closed host handle");
  return file;
}
export function fileSize(id) {
  return fs.fstatSync(get(id).fd).size;
}
export function readAt(id, offset, length) {
  const bytes = Buffer.allocUnsafe(length);
  let got = 0;
  while (got < length) {
    const n = fs.readSync(get(id).fd, bytes, got, length - got, offset + got);
    if (!n) throw new Error("Short positioned read");
    got += n;
  }
  return bytes;
}
export function writeAt(id, offset, bytes) {
  let written = 0;
  while (written < bytes.length)
    written += fs.writeSync(
      get(id).fd,
      bytes,
      written,
      bytes.length - written,
      offset + written,
    );
}
export function closeHandle(id) {
  const file = handles.get(id);
  if (!file) return;
  handles.delete(id);
  try {
    fs.closeSync(file.fd);
  } finally {
    if (file.dir) fs.rmSync(file.dir, { recursive: true });
  }
}
export function temporary() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "thereabouts-"));
  try {
    const fd = fs.openSync(path.join(dir, "spool"), "wx+");
    const id = ++sequence;
    handles.set(id, { fd, dir });
    return id;
  } catch (e) {
    fs.rmSync(dir, { recursive: true });
    throw e;
  }
}
export function readLine() {
  if (output.readLine && output.readLine !== readLine) return output.readLine();
  return stdinLine();
}

export function stdout(value) {
  output.stdout(value);
}
export function stderr(value) {
  output.stderr(value);
}
export function withIo(io, fn) {
  const previous = output;
  output = io;
  try {
    return fn();
  } finally {
    output = previous;
  }
}
export function handleCount() {
  return handles.size;
}

export function terminalColumns() {
  const columns = Number(output.env?.COLUMNS);
  if (Number.isInteger(columns) && columns > 0 && columns <= 10_000)
    return columns;
  return output.columns > 0 ? output.columns : 80;
}
