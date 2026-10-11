// Run every sample CSV in examples/data through the matching lookup and print a match table.
//
// Needs: thereabouts data install core postal airports ip locode phone plates
// Run:   node examples/node/batch_csv.mjs [--data-dir DIR] [--csv-dir DIR] [--limit N]
// Each row is compared with its expected answer. A mismatch is printed, never thrown.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { DataNotInstalledError, Geocoder, ThereaboutsError } from "thereabouts";

const defaultCsvDir = join(dirname(fileURLToPath(import.meta.url)), "..", "data");

// Minimal RFC 4180 reader: quoted fields, doubled quotes, embedded commas.
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') (field += '"'), i++;
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") (row.push(field), (field = ""));
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((v) => v !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) (row.push(field), rows.push(row));
  const [header, ...body] = rows;
  return body.map((values) => Object.fromEntries(header.map((h, i) => [h, values[i] ?? ""])));
}

const countries = (r) => {
  const found = new Set(r.country ? [r.country.code] : []);
  for (const c of r.candidates) if (c.country) found.add(c.country.code);
  return found;
};

function verdict(r, expected) {
  if (expected === "") return r.status === "not_found" ? "ok" : "MISMATCH";
  if (r.status === "matched" && countries(r).has(expected)) return "ok";
  if (r.status === "ambiguous" && countries(r).has(expected)) return "ok (ambiguous)";
  return "MISMATCH";
}

const place = (r) => r.city?.name ?? r.country?.name ?? "-";

// Each handler yields [input, expected, got, verdict] for every row.
async function* cityPoints(geo, rows) {
  const points = rows.map((r) => ({ lat: Number(r.lat), lon: Number(r.lon) }));
  let i = 0;
  for await (const result of geo.reverseMany(points)) {
    const row = rows[i++];
    const accepted = new Set([row.expected_city, ...row.accepted_names.split("|").filter(Boolean)]);
    const got = result.city?.name ?? null;
    const code = result.country?.code ?? null;
    const ok = accepted.has(got) && code === row.expected_country;
    yield [row.id, row.expected_city, `${got}/${code}`, ok ? "ok" : "MISMATCH"];
  }
}

const forward = (call, key, expectedLabel) =>
  async function* (geo, rows) {
    for (const row of rows) {
      const r = await call(geo, row);
      const got = `${r.status}: ${place(r)}/${[...countries(r)].sort().join(",") || "-"}`;
      yield [row[key], row[expectedLabel], got, verdict(r, row.expected_country)];
    }
  };

const FAMILIES = {
  "city_points.csv": cityPoints,
  "postal.csv": forward((g, r) => g.postal(r.code, { country: r.country }), "code", "expected_city"),
  "airports.csv": forward((g, r) => g.airport(r.code, { scheme: r.scheme }), "code", "expected_name_contains"),
  "locode.csv": forward((g, r) => g.locode(r.code), "code", "expected_name"),
  "phone.csv": forward((g, r) => g.phone(r.number), "number", "expected_country"),
  "ip.csv": forward((g, r) => g.ip(r.address), "address", "note"),
  "plates.csv": forward((g, r) => g.plate(r.plate), "plate", "expected_country"),
};

const { values } = parseArgs({
  options: {
    "data-dir": { type: "string" },
    "csv-dir": { type: "string", default: defaultCsvDir },
    limit: { type: "string" },
  },
});
const limit = values.limit === undefined ? undefined : Number(values.limit);

const totals = { ok: 0, mismatch: 0 };
const geo = await Geocoder.open({ dataDir: values["data-dir"] });
try {
  for (const [name, handler] of Object.entries(FAMILIES)) {
    const path = join(values["csv-dir"], name);
    if (!existsSync(path)) continue;
    const rows = parseCsv(readFileSync(path, "utf8")).slice(0, limit);
    console.log(`\n== ${name} (${rows.length} rows) ==`);
    console.log(`${"input".padEnd(22)} ${"expected".padEnd(26)} ${"got".padEnd(40)} verdict`);
    try {
      for await (const [key, expected, got, status] of handler(geo, rows)) {
        totals[status.startsWith("ok") ? "ok" : "mismatch"]++;
        console.log(`${key.slice(0, 22).padEnd(22)} ${expected.slice(0, 26).padEnd(26)} ${got.slice(0, 40).padEnd(40)} ${status}`);
      }
    } catch (error) {
      if (error instanceof DataNotInstalledError) console.log(`(skipped, pack not installed: ${error.message})`);
      else if (error instanceof ThereaboutsError) console.log(`(error: ${error.message})`);
      else throw error;
    }
  }
} finally {
  await geo.close();
}
console.log(`\nsummary: ${totals.ok} ok, ${totals.mismatch} mismatch`);
