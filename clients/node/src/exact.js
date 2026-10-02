import { inflate } from "node:zlib";
import { promisify } from "node:util";
import { u64 } from "./container.js";
import { CorruptPackError, check } from "./errors.js";
import { compare, parse, utf8 } from "./json.js";
import { compound, countryCode, normalize } from "./keys.js";
import { codePayload } from "./code-validation.js";

const decompress = promisify(inflate);
async function entry(shard, index) {
  const { file, sections: s } = shard;
  const bytes = await file.read(s[8].start + index * 40, 40);
  const keyOffset = u64(bytes, 0),
    keyLength = bytes.readUInt32LE(8);
  const candidates = bytes.readUInt32LE(12),
    offset = u64(bytes, 16),
    length = u64(bytes, 24),
    rawLength = u64(bytes, 32);
  check(
    keyLength > 0 &&
      candidates > 0 &&
      length > 0 &&
      rawLength > 0 &&
      rawLength <= shard.record.max_record_bytes,
    "Invalid exact record size",
  );
  check(
    keyOffset + keyLength <= s[9].length && offset + length <= s[10].length,
    "Invalid exact record bounds",
  );
  const key = utf8(await file.read(s[9].start + keyOffset, keyLength));
  return { key, keyOffset, keyLength, candidates, offset, length, rawLength };
}
export async function exactHeader(shard) {
  check(
    shard.sections[8].count === shard.record.count,
    "Exact inventory count mismatch",
  );
  const first = await entry(shard, 0),
    last = await entry(shard, shard.record.count - 1);
  check(
    first.key === shard.record.first_key && last.key === shard.record.last_key,
    "Exact inventory range mismatch",
  );
}
async function payload(pack, shard, row) {
  const bytes = await shard.file.read(
    shard.sections[10].start + row.offset,
    row.length,
  );
  let inflated;
  try {
    inflated = await decompress(bytes, {
      maxOutputLength: row.rawLength + 1,
      info: true,
    });
  } catch (error) {
    if (error?.code?.startsWith("Z_") || error?.code === "ERR_BUFFER_TOO_LARGE")
      throw new CorruptPackError("Invalid compressed record", { cause: error });
    throw error;
  }
  check(
    inflated.engine.bytesWritten === bytes.length &&
      inflated.buffer.length === row.rawLength,
    "Compressed length mismatch or trailing stream",
  );
  const value = parse(inflated.buffer);
  codePayload(value, pack.manifest.place_count);
  check(value.candidates.length === row.candidates, "Candidate count mismatch");
  return value.candidates;
}
export async function exactLookup(pack, wanted) {
  const shard = pack.exacts.find(
    (s) =>
      compare(s.record.first_key, wanted) <= 0 &&
      compare(wanted, s.record.last_key) <= 0,
  );
  if (!shard) return [];
  let low = 0,
    high = shard.record.count;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    const row = await entry(shard, middle);
    const order = compare(row.key, wanted);
    if (order === 0) return payload(pack, shard, row);
    if (order < 0) low = middle + 1;
    else high = middle;
  }
  return [];
}
export async function verifyExact(pack) {
  for (const shard of pack.exacts) {
    let keyOffset = 0,
      offset = 0,
      previous = "",
      maximum = 0;
    for (let index = 0; index < shard.record.count; index++) {
      const row = await entry(shard, index);
      check(
        row.keyOffset === keyOffset &&
          row.offset === offset &&
          compare(previous, row.key) < 0,
        "Unordered or noncontiguous exact records",
      );
      const parts = row.key.split("\0");
      const postal = pack.manifest.family === "postal";
      check(parts.length === (postal ? 2 : 3), "Invalid compound key");
      const scheme = postal ? null : parts.shift();
      const country = parts[0] ? countryCode(parts[0]) : null;
      const code = normalize(
        parts[1],
        pack.manifest.key_normalization,
        country,
      );
      check(
        compound(pack.manifest.family, code, country, scheme) === row.key,
        "Noncanonical key",
      );
      await payload(pack, shard, row);
      keyOffset += row.keyLength;
      offset += row.length;
      previous = row.key;
      maximum = Math.max(maximum, row.rawLength);
    }
    check(
      keyOffset === shard.sections[9].length &&
        offset === shard.sections[10].length &&
        maximum === shard.record.max_record_bytes,
      "Incomplete exact sections",
    );
  }
}
