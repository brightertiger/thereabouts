// Forward lookups: names, postal codes, airports, UN/LOCODEs, phone numbers, IPs, plates.
//
// Needs: thereabouts data install core postal airports ip locode phone plates
// Run:   node examples/node/forward.mjs [--data-dir DIR]
// A family that is not installed is reported and skipped.
import { parseArgs } from "node:util";
import { DataNotInstalledError, Geocoder, ThereaboutsError } from "thereabouts";

const line = (r) => {
  let text =
    `${r.status.padEnd(13)} match=${r.match} city=${r.city?.name ?? null} ` +
    `country=${r.country?.code ?? null}`;
  if (r.candidates.length) {
    const shown = r.candidates
      .slice(0, 4)
      .map((c) => `${c.city?.name ?? "?"}/${c.country?.code ?? "?"}`)
      .join(", ");
    text += ` | ${r.candidates.length} candidates (ranked by ${r.rank_basis}): ${shown}`;
  }
  if (r.hint) text += ` | hint: ${r.hint}`;
  return text;
};

// Run [label, async call] pairs; keep going when a family is missing.
async function section(title, calls) {
  console.log(`\n== ${title} ==`);
  for (const [label, call] of calls) {
    try {
      console.log(`${label.padEnd(34)} ${line(await call())}`);
    } catch (error) {
      if (error instanceof DataNotInstalledError) {
        console.log(`(skipped, pack not installed: ${error.message})`);
        return;
      }
      if (!(error instanceof ThereaboutsError)) throw error;
      console.log(`${label.padEnd(34)} error: ${error.message}`);
    }
  }
}

const { values } = parseArgs({ options: { "data-dir": { type: "string" } } });
const geo = await Geocoder.open({ dataDir: values["data-dir"] });

try {
  await section("geocode: towns and cities by name (no street addresses)", [
    ["Paris, FR", () => geo.geocode("Paris", { country: "FR" })],
    ["Springfield (ambiguous)", () => geo.geocode("Springfield", { country: "US", limit: 5 })],
    ["Springfield, prefer population", () => geo.geocode("Springfield", { country: "US", prefer: "population" })],
    ["Pariss (fuzzy)", () => geo.geocode("Pariss", { country: "FR" })],
    ["12 Main Street", () => geo.geocode("12 Main Street")],
  ]);
  await section("postal: the country is required", [
    ["75001, FR", () => geo.postal("75001", { country: "FR" })],
    ["10001, US", () => geo.postal("10001", { country: "US" })],
    ["10001 without country", () => geo.postal("10001")],
  ]);
  await section("airport: IATA then ICAO unless a scheme is given", [
    ["CDG", () => geo.airport("CDG")],
    ["LHR, scheme=iata", () => geo.airport("LHR", { scheme: "iata" })],
    ["KJFK, scheme=icao", () => geo.airport("KJFK", { scheme: "icao" })],
  ]);
  await section("locode: five characters, or three plus a country", [
    ["BEANR", () => geo.locode("BEANR")],
    ["ANR, country=BE", () => geo.locode("ANR", { country: "BE" })],
  ]);
  await section("phone: international E.164 with a leading +", [
    ["+32 2 555 1234", () => geo.phone("+32 2 555 1234")],
    ["+1 415 555 2671 (shared code)", () => geo.phone("+1 415 555 2671")],
    ["0032 2 555 1234 (no plus)", () => geo.phone("0032 2 555 1234")],
  ]);
  await section("ip: IPv4 or IPv6 literal", [
    ["8.8.8.8", () => geo.ip("8.8.8.8")],
    ["2001:4860:4860::8888", () => geo.ip("2001:4860:4860::8888")],
    ["192.0.2.1 (documentation)", () => geo.ip("192.0.2.1")],
  ]);
  await section("plate: format evidence, not a register", [
    ["VU52 BWO", () => geo.plate("VU52 BWO")],
    ["05-GJV-1", () => geo.plate("05-GJV-1")],
    ["05-GJV-1, country=NL", () => geo.plate("05-GJV-1", { country: "NL" })],
    ["SCF 6045P", () => geo.plate("SCF 6045P")],
  ]);
} finally {
  await geo.close();
}
