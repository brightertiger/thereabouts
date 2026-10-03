import { check, integer, UnsupportedPackError } from "./errors.js";

const layouts = {
  cells: [
    [1, 40],
    [2, 2],
    [3, 1],
    [4, 16],
  ],
  catalogue: [
    [5, 64],
    [6, 8],
    [7, 1],
  ],
  exact: [
    [8, 40],
    [9, 1],
    [10, 1],
  ],
};
const kinds = { cells: 1, catalogue: 2, exact: 3 };
export function u64(bytes, offset) {
  return integer(Number(bytes.readBigUInt64LE(offset)));
}
export async function container(file, kind) {
  const layout = layouts[kind];
  const header = await file.read(0, 32 + 32 * layout.length);
  check(
    header.subarray(0, 8).equals(Buffer.from("THEREPK\0")),
    "Invalid container magic",
  );
  if (
    header.readUInt16LE(8) !== 1 ||
    header.readUInt16LE(10) !== 0 ||
    header.readUInt32LE(12) !== 0
  )
    throw new UnsupportedPackError("Unsupported container format");
  check(
    header.readUInt32LE(16) === kinds[kind] &&
      header.readUInt32LE(20) === layout.length,
    "Wrong container kind",
  );
  check(u64(header, 24) === file.size, "Container length mismatch");
  const sections = {};
  let end = header.length;
  for (let i = 0; i < layout.length; i++) {
    const [id, width] = layout[i];
    const offset = 32 + 32 * i;
    check(
      header.readUInt32LE(offset) === id &&
        header.readUInt32LE(offset + 4) === 0,
      "Invalid section flags or order",
    );
    const start = u64(header, offset + 8),
      length = u64(header, offset + 16),
      count = u64(header, offset + 24);
    check(
      start === Math.ceil(end / 8) * 8 &&
        length === count * width &&
        Number.isSafeInteger(start + length) &&
        start + length <= file.size,
      "Invalid section bounds",
    );
    check(
      (await file.read(end, start - end)).every((byte) => byte === 0),
      "Nonzero alignment padding",
    );
    sections[id] = { start, length, count };
    end = start + length;
  }
  check(end === file.size, "Trailing container bytes");
  return sections;
}
