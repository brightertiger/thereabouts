// Reverse geocoding: coordinates and H3 cells to country, state, city and timezone.
//
// Needs the core pack:  thereabouts data install core
// Run:                  node examples/node/reverse.mjs [--data-dir DIR]
import { parseArgs } from "node:util";
import { DataNotInstalledError, Geocoder } from "thereabouts";

const PLACES = [
  ["Eiffel Tower, Paris", 48.8584, 2.2945],
  ["Shinjuku, Tokyo", 35.6896, 139.7006],
  ["Brooklyn Bridge, New York", 40.7061, -73.9969],
  ["Gateway of India, Mumbai", 18.922, 72.8347],
  ["Howrah Bridge, Howrah", 22.5851, 88.3468],
  ["Arabian Sea, off Mumbai", 19.0, 72.6],
];

const line = (r) =>
  `${r.status.padEnd(13)} match=${r.match} city=${r.city?.name ?? null} ` +
  `state=${r.state?.name ?? null} country=${r.country?.code ?? null} tz=${r.timezone}`;

const { values } = parseArgs({ options: { "data-dir": { type: "string" } } });

let geo;
try {
  geo = await Geocoder.open({ dataDir: values["data-dir"] });
} catch (error) {
  if (error instanceof DataNotInstalledError) {
    console.error(`Data missing: ${error.message}`);
    process.exit(3);
  }
  throw error;
}

try {
  console.log("== reverse({lat, lon}) ==");
  for (const [name, lat, lon] of PLACES) {
    console.log(`${name.padEnd(28)} ${line(await geo.reverse({ lat, lon }))}`);
  }

  console.log("\n== a nearest or distant match reports a distance band ==");
  const remote = await geo.reverse({ lat: 46.5, lon: -109.5 }); // rural Montana
  console.log(line(remote), "| band:", remote.distance_band);

  console.log("\n== evidence explains the answer (or the miss) ==");
  const ocean = await geo.reverse({ lat: 19.0, lon: 72.6, evidence: true });
  console.log(line(ocean), "| reason:", ocean.evidence?.reason);

  console.log("\n== invalid input is a result, not an exception ==");
  const bad = await geo.reverse({ lat: 95, lon: 0 });
  console.log(line(bad), "| hint:", bad.hint);

  console.log("\n== fromH3: the stored ancestor of a cell (resolution 0 to 8) ==");
  const paris = await geo.reverse({ lat: 48.8566, lon: 2.3522 });
  console.log("cell of Paris centre:", paris.cell);
  console.log(line(await geo.fromH3(paris.cell)));
  console.log(line(await geo.fromH3("881fb46625fffff")));

  console.log("\n== reverseMany: named lat/lon objects, results in order ==");
  const points = PLACES.slice(0, 3).map(([, lat, lon]) => ({ lat, lon }));
  for await (const result of geo.reverseMany(points)) {
    console.log(result.city?.name ?? null);
  }

  console.log("\n== the full JSON contract of one result ==");
  console.log(JSON.stringify(await geo.reverse({ lat: 48.8584, lon: 2.2945 }), null, 2));
} finally {
  await geo.close();
}
