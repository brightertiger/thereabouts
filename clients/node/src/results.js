import { AmbiguousResultError } from "./errors.js";
import { METHODS, methods, reference, storedCell } from "./address.js";
import { freeze } from "./json.js";
import { place, identity } from "./catalogue.js";

const BASIS = {
  city_polygon: "source_boundary",
  rural_polygon: "source_boundary",
  policy_polygon: "policy_boundary",
  urban_allocation: "inferred_urban",
  town_radius: "inferred_extent",
  rural_nearest: "nearest_settlement",
  rural_nearest_distant: "nearest_settlement",
};
export function requireOne(result) {
  if (result.status === "ambiguous")
    throw new AmbiguousResultError("Multiple candidates remain");
  return result.selected;
}
export function dataIdentity(manifest) {
  const result = {};
  for (const key of [
    "family",
    "catalogue_epoch",
    "manifest_sha256",
    "golden_sha256",
    "policy_sha256",
    "h3_version",
    "sources",
  ])
    result[key] = manifest[key];
  result.version = manifest.data_version;
  return freeze(result);
}
async function places(pack, refs) {
  const country = await place(pack, refs[0]);
  const state = await place(pack, refs[1]),
    city = await place(pack, refs[2]);
  const sovereign = country ? await place(pack, country.sovereign) : null;
  return {
    country: country?.place ?? null,
    state: state?.place ?? null,
    city: city?.place ?? null,
    sovereign: sovereign?.place ?? null,
  };
}
function band(pack, method) {
  if (!["rural_nearest", "rural_nearest_distant"].includes(method)) return null;
  const { distant_over_m: lower, cutoff_m: upper } = pack.manifest.nearest;
  const distant = method === "rural_nearest_distant";
  return {
    greater_than_m: distant ? lower : null,
    at_most_m: distant ? upper : lower,
    cutoff_m: upper,
    exact_m: null,
  };
}
export async function reverseResult(pack, input, block, covered, hit) {
  let selected = null;
  const warnings = [];
  if (hit && hit.label.slice(0, 3).some(Boolean)) {
    const context = await places(pack, hit.label);
    const method = METHODS[hit.label[3] & 7];
    selected = {
      id: (context.city ?? context.state ?? context.country).id,
      place: null,
      ...context,
      relationship: "spatial_context",
      methods: methods(hit.label[3]),
      confidence: {
        basis:
          BASIS[method] ??
          (context.country || context.state ? "source_boundary" : "unknown"),
        calibrated_probability: null,
      },
      distance: band(pack, method),
      accuracy_m: null,
      observations: [],
    };
    if (method === "rural_nearest_distant")
      warnings.push({ code: "distant_nearest" });
    if (["urban_allocation", "town_radius"].includes(method))
      warnings.push({ code: "inferred_extent" });
  }
  return freeze({
    status: !covered
      ? "outside_coverage"
      : !hit
        ? "ineligible"
        : !selected
          ? "unassigned"
          : "matched",
    selected,
    candidates: selected ? [selected] : [],
    query: input.query,
    reference: reference(input.cell, hit ? storedCell(block, hit.key) : null),
    data: pack.data,
    warnings,
    error: null,
  });
}
async function observation(pack, row) {
  const result = {};
  for (const name of [
    "source",
    "source_id",
    "source_release",
    "license",
    "golden_table",
    "fields",
    "cell_status",
    "country_disagrees",
  ])
    result[name] = row[name];
  result.reference =
    row.reference === null
      ? null
      : reference(row.reference.h3, row.reference.stored_h3);
  const names = ["country_id", "state_id", "city_id"];
  for (let i = 0; i < 3; i++)
    result[names[i]] = await identity(pack, row.refs[i]);
  result.methods = methods(row.flags, row.reference?.stored_h3 != null);
  return result;
}
export async function codeMatches(pack, rows) {
  const candidates = [],
    warnings = new Set();
  for (const row of rows) {
    const context = await places(pack, row.refs);
    const observations = [];
    for (const item of row.observations)
      observations.push(await observation(pack, item));
    candidates.push({
      id: row.id,
      place: row.entity,
      ...context,
      relationship: "source_association",
      methods: row.methods,
      confidence: { basis: "exact_code_link", calibrated_probability: null },
      distance: row.distance,
      accuracy_m: null,
      observations,
    });
    for (const code of row.warnings) warnings.add(code);
  }
  return freeze({
    candidates,
    warnings: [...warnings].sort().map((code) => ({ code })),
  });
}
export function codeResult(pack, query, matches) {
  const { candidates, warnings } = matches;
  const selected = candidates.length === 1 ? candidates[0] : null;
  return freeze({
    status: selected
      ? "matched"
      : candidates.length
        ? "ambiguous"
        : "not_found",
    selected,
    candidates,
    query,
    reference: null,
    data: pack.data,
    warnings,
    error: null,
  });
}
