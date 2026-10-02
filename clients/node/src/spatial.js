import { setImmediate } from "node:timers/promises";
import h3 from "h3-js";
import { u64 } from "./container.js";
import { OFFSETS, labelCheck, storedCell } from "./address.js";
import { check } from "./errors.js";

export async function spatialDirectory(shard, blocks) {
  const { file, sections: s, record } = shard;
  check(s[1].count <= 41162, "Too many H3 blocks");
  const bytes = await file.read(s[1].start, s[1].length);
  let previous = -1,
    keys = 0,
    values = 0,
    dictionary = 0;
  for (let p = 0; p < bytes.length; p += 40) {
    const block = bytes.readUInt32LE(p),
      count = bytes.readUInt32LE(p + 4);
    const width = bytes.readUInt32LE(p + 16),
      labels = bytes.readUInt32LE(p + 20);
    check(
      previous < block &&
        block < 41846 &&
        !blocks.has(block) &&
        h3.isValidCell(storedCell(block, 0)),
      "Invalid block directory",
    );
    check(count <= 16807 && [0, 1, 2].includes(width), "Invalid block layout");
    check(
      width === 0
        ? labels === 0
        : labels > 0 && labels <= (width === 1 ? 256 : 65536),
      "Invalid label dictionary size",
    );
    check(count > 0 || width === 0, "Empty block must be flat");
    check(
      u64(bytes, p + 8) === keys &&
        u64(bytes, p + 24) === values &&
        u64(bytes, p + 32) === dictionary,
      "Noncontiguous block spans",
    );
    const entry = {
      shard,
      block,
      count,
      width,
      labels,
      keys,
      values,
      dictionary,
    };
    keys += count * 2;
    values += count * (width || 16);
    dictionary += labels * 16;
    blocks.set(block, entry);
    previous = block;
  }
  check(
    keys === s[2].length &&
      values === s[3].length &&
      dictionary === s[4].length,
    "Incomplete spatial sections",
  );
  check(
    bytes.length > 0 &&
      bytes.readUInt32LE(0) === record.first_block &&
      previous === record.last_block,
    "Cell inventory range mismatch",
  );
}
function labelAt(bytes, position) {
  return [0, 4, 8, 12].map((offset) => bytes.readUInt32LE(position + offset));
}
function numericCompare(a, b) {
  for (let i = 0; i < 4; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}
export async function loadBlock(entry, cache, placeCount) {
  const cached = cache.get(`block:${entry.block}`);
  if (cached) return cached;
  const { file, sections: s } = entry.shard;
  const keys = await file.read(s[2].start + entry.keys, entry.count * 2);
  const values = await file.read(
    s[3].start + entry.values,
    entry.count * (entry.width || 16),
  );
  const dictionary = await file.read(
    s[4].start + entry.dictionary,
    entry.labels * 16,
  );
  const seen = new Set();
  let previous = -1;
  for (let i = 0; i < entry.count; i++) {
    if (i && i % 256 === 0) await setImmediate();
    const key = keys.readUInt16LE(i * 2);
    check(
      key > previous &&
        key <= 19607 &&
        h3.isValidCell(storedCell(entry.block, key)),
      "Invalid stored key",
    );
    let depth = 5;
    while (key < OFFSETS[depth]) depth--;
    let digits = key - OFFSETS[depth];
    while (depth > 0) {
      digits = Math.floor(digits / 7);
      depth--;
      check(!seen.has(OFFSETS[depth] + digits), "Overlapping stored ancestors");
    }
    seen.add(key);
    previous = key;
    if (entry.width) {
      const selector =
        entry.width === 1 ? values[i] : values.readUInt16LE(i * 2);
      check(selector < entry.labels, "Invalid dictionary selector");
    } else labelCheck(labelAt(values, i * 16), placeCount);
  }
  let last = null;
  for (let i = 0; i < entry.labels; i++) {
    const label = labelAt(dictionary, i * 16);
    labelCheck(label, placeCount);
    check(
      last === null || numericCompare(last, label) < 0,
      "Unsorted label dictionary",
    );
    last = label;
  }
  return cache.put(`block:${entry.block}`, { keys, values, dictionary });
}
export function lookup(entry, bytes, suffix) {
  for (let depth = 5; depth >= 0; depth--) {
    const key = OFFSETS[depth] + suffix;
    let low = 0,
      high = entry.count;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (bytes.keys.readUInt16LE(middle * 2) < key) low = middle + 1;
      else high = middle;
    }
    if (low < entry.count && bytes.keys.readUInt16LE(low * 2) === key) {
      const selector =
        entry.width === 1
          ? bytes.values[low]
          : entry.width === 2
            ? bytes.values.readUInt16LE(low * 2)
            : low;
      return {
        key,
        label: labelAt(
          entry.width ? bytes.dictionary : bytes.values,
          selector * 16,
        ),
      };
    }
    suffix = Math.floor(suffix / 7);
  }
  return null;
}
