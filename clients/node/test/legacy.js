// Assert the unchanged legacy file, with only the documented migration allowances.
import assert from "node:assert/strict";
export function assertLegacy(result, original, cases) {
  let c = original;
  if (c.id === 52)
    c = {
      id: c.id,
      request: c.request,
      result: cases.find((v) => v.id === 32).result,
    };
  const reverse = ["h3", "coordinates"].includes(c.request.kind);
  if (c.id === 47) {
    assert.equal(c.error.name, "InvalidInputError");
    assert.equal(result.status, "not_found");
    assert.equal(result.evidence.reason, "no_stored_ancestor");
    return "coarse_cell_intended_change";
  }
  if (c.error) {
    assert.ok(
      ["ContextRequiredError", "InvalidInputError"].includes(c.error.name),
    );
    assert.equal(result.status, "invalid_input");
    return "invalid_input";
  }
  const old = c.result;
  if (reverse && old.status !== "matched") {
    assert.equal(result.status, "not_found");
    assert.equal(
      result.evidence.reason,
      {
        unassigned: "unassigned",
        ineligible: "no_land",
        outside_coverage: "outside_coverage",
      }[old.status],
    );
    for (const f of ["country", "state", "city"]) assert.equal(result[f], null);
    return old.status;
  }
  assert.equal(result.status, old.status);
  if (old.status === "not_found") {
    for (const f of ["country", "state", "city"]) assert.equal(result[f], null);
    return "not_found";
  }
  const answers = result.status === "ambiguous" ? result.candidates : [result];
  const previous = reverse ? [old.selected] : old.candidates;
  assert.equal(answers.length, previous.length);
  for (const answer of answers) {
    const identity = reverse
      ? old.selected.id
      : answer.city && c.request.kind === "postal"
        ? answer.city.id
        : `${c.request.kind}:${answer.evidence.source_ids[0].source}:${answer.evidence.source_ids[0].source_id}`;
    const before = previous.find((p) => p.id === identity);
    assert.ok(before, identity);
    for (const f of ["country", "state", "city"]) {
      assert.equal(answer.evidence[f + "_id"], before[f]?.id ?? null);
      if (!before[f]) {
        if (c.id === 29 && f === "country") {
          assert.equal(answer.country.code, "AA");
          assert.equal(answer.evidence.reason, "country_from_key");
        } else assert.equal(answer[f], null);
      } else {
        const expected =
          f === "city" && before[f].id === "city:synthetic:A"
            ? "München 東京"
            : before[f].name;
        if (f === "city" && before[f].id === "city:synthetic:A")
          assert.equal(before[f].name, "München 東京 city:synthetic:A");
        assert.equal(answer[f].name, expected);
        if (f === "country")
          assert.equal(answer[f].code, before[f].country_code);
        if (f === "city") assert.equal(answer.city.id, before.city.id);
        if (!reverse && f === "state" && before[f].id === "state:synthetic:A") {
          assert.equal(before[f].code, null);
          assert.equal(answer.state.code, "AA.A");
        }
      }
    }
    if (reverse) {
      const method = before.methods.city;
      assert.equal(
        answer.match,
        { rural_nearest: "nearest", rural_nearest_distant: "nearest_distant" }[
          method
        ] ?? "contained",
      );
      assert.equal(answer.evidence.city_method, method);
      assert.equal(answer.evidence.land_method, before.methods.land);
    } else {
      assert.equal(answer.match, "exact");
      const observations = [...before.observations].sort((a, b) => {
        const key = (v) =>
          [
            v.source,
            v.source_id,
            v.fields.name || v.fields.place_name || "",
          ].join("\0");
        return key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0;
      });
      const anchor = observations[0].fields;
      if (anchor.latitude === null) assert.equal(answer.point, null);
      else {
        assert.ok(Math.abs(answer.point.lat - anchor.latitude) <= 0.00000051);
        assert.ok(Math.abs(answer.point.lon - anchor.longitude) <= 0.00000051);
      }
      const pairs = (v) =>
        v.map((s) => [s.source, s.source_id].join("\0")).sort();
      assert.deepEqual(
        [...new Set(pairs(answer.evidence.source_ids))],
        [...new Set(pairs(observations))],
      );
    }
  }
  if (result.status === "ambiguous")
    for (const f of [
      "country",
      "state",
      "city",
      "point",
      "timezone",
      "cell",
      "match",
    ]) {
      const first = result.candidates[0][f],
        common = result.candidates.every(
          (a) => JSON.stringify(a[f]) === JSON.stringify(first),
        );
      assert.deepEqual(result[f], common ? first : null);
    }
  return result.status;
}
