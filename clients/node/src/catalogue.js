import { u64 } from "./container.js";
import { check, fields, string } from "./errors.js";
import { freeze, parse, utf8, compare } from "./json.js";
import { relative } from "./files.js";

const names = [
  "id",
  "name",
  "name_en",
  "local_name",
  "role",
  "settlement_kind",
  "country_code",
  "code",
  "code_status",
  "parent_method",
  "normalization_method",
  "evidence",
];
const links = ["country_id", "parent_id", "sovereign_id", "normalized_city_id"];
export async function poolString(shard, ref) {
  if (!ref) return null;
  const { file, sections: s } = shard;
  check(ref < s[6].count - 1, "Invalid string reference");
  const offsets = await file.read(s[6].start + ref * 8, 16);
  const start = u64(offsets, 0),
    end = u64(offsets, 8);
  check(start <= end && end <= s[7].length, "Invalid string span");
  return utf8(await file.read(s[7].start + start, end - start));
}
export async function catalogueHeader(shard) {
  const { file, sections: s, record } = shard;
  check(
    s[5].count === record.count && s[6].count >= 2,
    "Catalogue inventory mismatch",
  );
  const first = await file.read(s[6].start, 16);
  const last = await file.read(s[6].start + s[6].length - 8, 8);
  check(
    u64(first, 0) === 0 && u64(first, 8) === 0 && u64(last, 0) === s[7].length,
    "Invalid string pool endpoints",
  );
}
export async function placeRow(pack, ref) {
  check(
    Number.isInteger(ref) && ref > 0 && ref <= pack.manifest.place_count,
    "Invalid place reference",
  );
  const shard = pack.catalogues.find(
    (s) => s.record.first_id <= ref && ref < s.record.first_id + s.record.count,
  );
  const bytes = await shard.file.read(
    shard.sections[5].start + (ref - shard.record.first_id) * 64,
    64,
  );
  return {
    shard,
    words: Array.from({ length: 16 }, (_, i) => bytes.readUInt32LE(i * 4)),
  };
}
export async function identity(pack, ref) {
  if (!ref) return null;
  const cached = pack.decoded.get(`id:${ref}`);
  if (cached !== undefined) return cached;
  const { shard, words } = await placeRow(pack, ref);
  const id = string(await poolString(shard, words[0]));
  pack.decoded.put(`id:${ref}`, id);
  return id;
}
export async function place(pack, ref) {
  if (!ref) return null;
  const cached = pack.decoded.get(ref);
  if (cached) return cached;
  const { shard, words } = await placeRow(pack, ref);
  const result = {};
  for (let i = 0; i < names.length; i++)
    result[names[i]] = await poolString(shard, words[i]);
  for (const name of [
    "id",
    "name",
    "role",
    "settlement_kind",
    "country_code",
    "evidence",
  ])
    string(result[name]);
  check(
    ["country", "state", "district", "city", "town", "settlement"].includes(
      result.role,
    ),
    "Invalid place role",
  );
  const evidence = parse(Buffer.from(result.evidence));
  fields(evidence, ["golden_table", "source_ids", "name_provenance"]);
  relative(evidence.golden_table);
  result.evidence = evidence;
  for (let i = 0; i < links.length; i++)
    result[links[i]] = await identity(pack, words[12 + i]);
  result.code_system = null;
  const entry = freeze({ place: result, sovereign: words[14] });
  pack.decoded.put(ref, entry);
  return entry;
}
export async function verifyCatalogue(pack) {
  let previous = "";
  for (const shard of pack.catalogues) {
    for (let ref = 1; ref < shard.sections[6].count - 1; ref++)
      await poolString(shard, ref);
    for (
      let ref = shard.record.first_id;
      ref < shard.record.first_id + shard.record.count;
      ref++
    ) {
      const entry = await place(pack, ref);
      check(compare(previous, entry.place.id) < 0, "Unsorted public place IDs");
      previous = entry.place.id;
    }
  }
}
