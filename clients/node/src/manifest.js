import {
  CorruptPackError,
  UnsupportedPackError,
  check,
  fields,
  integer,
  string,
} from "./errors.js";
import { artifact, digestFile, manifestBytes, relative } from "./files.js";
import { canonical, compare, parse, sha256 } from "./json.js";
import { normalization } from "./keys.js";

function checksum(value) {
  check(
    typeof value === "string" && /^[0-9a-f]{64}$/.test(value),
    "Invalid SHA256",
  );
}
function supported(condition, message) {
  if (!condition) throw new UnsupportedPackError(message);
}
function identity(value) {
  check(
    !Object.hasOwn(value, "manifest_sha256"),
    "Manifest cannot store its own hash",
  );
  fields(value.format, ["major", "minor", "required_features"]);
  for (const field of Object.values(value.format)) integer(field);
  supported(
    value.schema === "thereabouts-pack-1" &&
      canonical(value.format) ===
        canonical({ major: 1, minor: 0, required_features: 0 }),
    "Unsupported format",
  );
  supported(
    ["reverse", "postal", "airports"].includes(value.family),
    "Unsupported family",
  );
  supported(value.minimum_reader === "0.1.0", "Unsupported minimum reader");
  supported(
    integer(value.reference_resolution) === 8 &&
      integer(value.block_resolution) === 3,
    "Unsupported H3 resolutions",
  );
  for (const name of ["data_version", "catalogue_epoch", "h3_version"])
    string(value[name]);
  supported(value.h3_version.startsWith("4."), "Unsupported H3 version");
  supported(
    Array.isArray(value.dependencies) && !value.dependencies.length,
    "Unsupported dependencies",
  );
  for (const name of ["golden_sha256", "policy_sha256", "export_fingerprint"])
    checksum(value[name]);
  const nearest = value.nearest;
  check(
    integer(nearest.distant_over_m) < integer(nearest.cutoff_m, 1) &&
      nearest.exact_distance === false,
    "Invalid nearest bands",
  );
  const sourceKeys = [
    "source",
    "release",
    "license",
    "attribution",
    "source_url",
    "license_url",
  ];
  check(
    Array.isArray(value.sources) && value.sources.length,
    "Missing attribution",
  );
  const identities = new Set();
  for (const source of value.sources) {
    fields(source, sourceKeys);
    for (const field of sourceKeys) string(source[field]);
    const key = canonical([source.source, source.release]);
    check(!identities.has(key), "Repeated source release");
    identities.add(key);
  }
  const exported = value.export;
  check(
    exported &&
      exported.implementation &&
      !Array.isArray(exported.implementation),
    "Invalid exporter identity",
  );
  for (const [path, hash] of Object.entries(exported.implementation)) {
    relative(path);
    checksum(hash);
  }
  for (const notice of exported.release.notices) {
    relative(notice.path);
    integer(notice.size);
    checksum(notice.sha256);
  }
  check(
    sha256(canonical(exported)) === value.export_fingerprint &&
      exported.golden_sha256 === value.golden_sha256,
    "Mismatched export identity",
  );
  for (const name of ["data_version", "catalogue_epoch", "sources"]) {
    check(
      canonical(value[name]) === canonical(exported.release[name]),
      "Mismatched release metadata",
    );
  }
}
function inventory(value) {
  const exact = value.family !== "reverse";
  if (exact) {
    normalization(value.key_normalization);
    check(
      integer(value.unindexed_rows) <= integer(value.source_rows),
      "Invalid source accounting",
    );
    supported(
      value.candidate_policy === "source-observations-1",
      "Unsupported candidate policy",
    );
  }
  check(
    (exact ? ["keys"] : ["world", "blocks"]).includes(value.coverage),
    "Invalid coverage",
  );
  check(integer(value.place_count) <= 0xffffffff, "Invalid catalogue count");
  check(Array.isArray(value.files) && value.files.length, "Missing inventory");
  const paths = new Set();
  let next = 1,
    lastBlock = -1,
    lastKey = "",
    payloads = 0;
  for (const file of value.files) {
    relative(file.path);
    integer(file.size);
    checksum(file.sha256);
    check(
      file.path !== "manifest.json" && !paths.has(file.path),
      "Repeated or reserved artifact",
    );
    paths.add(file.path);
    if (file.kind === "catalogue") {
      check(integer(file.first_id, 1) === next, "Noncontiguous catalogue");
      next += integer(file.count, 1);
    } else if (file.kind === "cells") {
      check(
        !exact &&
          lastBlock < integer(file.first_block) &&
          file.first_block <= integer(file.last_block) &&
          file.last_block < 41846,
        "Invalid cell ranges",
      );
      lastBlock = file.last_block;
      payloads++;
    } else if (file.kind === "exact") {
      check(
        exact &&
          compare(lastKey, string(file.first_key)) < 0 &&
          compare(file.first_key, string(file.last_key)) <= 0,
        "Invalid exact ranges",
      );
      integer(file.count, 1);
      integer(file.max_record_bytes, 1);
      lastKey = file.last_key;
      payloads++;
    } else supported(file.kind === "notice", "Unsupported artifact kind");
  }
  check(next === value.place_count + 1 && payloads > 0, "Incomplete inventory");
  check(
    Array.isArray(value.notices) &&
      value.notices.length &&
      new Set(value.notices).size === value.notices.length,
    "Missing or duplicate notices",
  );
  check(
    canonical([...value.notices].sort(compare)) ===
      canonical(
        value.files
          .filter((f) => f.kind === "notice")
          .map((f) => f.path)
          .sort(compare),
      ),
    "Notice inventory mismatch",
  );
}
export async function readManifest(root, full = false) {
  try {
    const bytes = await manifestBytes(root);
    const value = parse(bytes);
    identity(value);
    inventory(value);
    for (const file of value.files) {
      const path = await artifact(root, file.path, file.size);
      if (full)
        check(
          (await digestFile(path)) === file.sha256,
          "Artifact checksum mismatch",
        );
    }
    return { ...value, manifest_sha256: sha256(bytes) };
  } catch (error) {
    if (
      error instanceof TypeError ||
      error instanceof RangeError ||
      error?.code?.startsWith("E")
    ) {
      throw new CorruptPackError("Invalid serving manifest", { cause: error });
    }
    throw error;
  }
}
