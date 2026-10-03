import h3 from "h3-js";
import { METHODS, labelCheck } from "./address.js";
import { check, fields, integer, string } from "./errors.js";
import { relative } from "./files.js";
import { compare } from "./json.js";
import { SCHEMES } from "./keys.js";

function refs(values, count) {
  check(
    Array.isArray(values) &&
      values.length === 3 &&
      values.every((n) => integer(n) <= count),
    "Invalid code references",
  );
}
function observation(row, count) {
  fields(row, [
    "source",
    "source_id",
    "source_release",
    "license",
    "golden_table",
    "fields",
    "reference",
    "refs",
    "flags",
    "cell_status",
    "country_disagrees",
  ]);
  for (const name of ["source", "source_id", "source_release", "license"])
    string(row[name]);
  relative(row.golden_table);
  check(
    row.fields !== null &&
      typeof row.fields === "object" &&
      !Array.isArray(row.fields),
    "Invalid observation fields",
  );
  refs(row.refs, count);
  labelCheck([...row.refs, integer(row.flags)], count);
  check(
    ["matched", "unassigned", "ineligible", "unlocated"].includes(
      row.cell_status,
    ),
    "Invalid observation status",
  );
  check(
    row.country_disagrees === null ||
      typeof row.country_disagrees === "boolean",
    "Invalid disagreement",
  );
  const point = row.reference;
  if (point === null) {
    check(
      row.cell_status === "unlocated" &&
        !row.refs.some(Boolean) &&
        row.flags === 0,
      "Missing located reference",
    );
    return;
  }
  fields(point, ["h3", "stored_h3"]);
  check(
    typeof point.h3 === "string" &&
      /^[0-9a-f]{15}$/.test(point.h3) &&
      h3.isValidCell(point.h3) &&
      h3.getResolution(point.h3) === 8,
    "Invalid observation H3",
  );
  if (point.stored_h3 !== null) {
    const cell = point.stored_h3;
    check(
      typeof cell === "string" &&
        /^[0-9a-f]{15}$/.test(cell) &&
        h3.isValidCell(cell),
      "Invalid stored H3",
    );
    const resolution = h3.getResolution(cell);
    check(
      resolution >= 3 &&
        resolution <= 8 &&
        h3.cellToParent(point.h3, resolution) === cell,
      "Invalid stored ancestor",
    );
  }
  check(
    (point.stored_h3 !== null) ===
      ["matched", "unassigned"].includes(row.cell_status),
    "Observation status/reference mismatch",
  );
}
export function codePayload(value, count) {
  fields(value, ["candidates"]);
  check(Array.isArray(value.candidates), "Invalid candidate list");
  let previous = "";
  for (const candidate of value.candidates) {
    fields(candidate, [
      "id",
      "entity",
      "refs",
      "methods",
      "distance",
      "observations",
      "warnings",
    ]);
    check(compare(previous, string(candidate.id)) < 0, "Unsorted candidates");
    previous = candidate.id;
    refs(candidate.refs, count);
    const method = candidate.methods;
    fields(method, ["city", "state", "country", "land"]);
    check(
      METHODS.includes(method.city) &&
        [null, "area"].includes(method.state) &&
        [null, "area"].includes(method.country) &&
        ["land", "offshore", "unknown"].includes(method.land),
      "Invalid methods",
    );
    const entity = candidate.entity;
    if (entity !== null) {
      fields(entity, ["id", "name", "role", "country_code", "codes", "type"]);
      check(
        entity.id === candidate.id && entity.role === "airport",
        "Invalid source entity",
      );
      fields(entity.codes, SCHEMES);
      for (const text of [
        entity.name,
        entity.country_code,
        entity.type,
        ...Object.values(entity.codes),
      ])
        check(
          text === null || typeof text === "string",
          "Invalid entity string",
        );
    }
    const distance = candidate.distance;
    if (distance !== null) {
      fields(distance, ["greater_than_m", "at_most_m", "cutoff_m", "exact_m"]);
      check(
        integer(distance.at_most_m, 1) <= integer(distance.cutoff_m, 1) &&
          (distance.greater_than_m === null ||
            integer(distance.greater_than_m) < distance.at_most_m) &&
          distance.exact_m === null,
        "Invalid distance band",
      );
    }
    check(
      Array.isArray(candidate.warnings) &&
        candidate.warnings.every((w) => typeof w === "string" && w.length > 0),
      "Invalid warnings",
    );
    check(
      Array.isArray(candidate.observations) &&
        candidate.observations.length > 0,
      "Missing observations",
    );
    for (const row of candidate.observations) observation(row, count);
  }
}
