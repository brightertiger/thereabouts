import {
  Geocoder,
  reverse,
  Result,
  Origin,
  DataNotInstalledError,
} from "thereabouts";
async function examples(): Promise<void> {
  const geo = await Geocoder.open({ dataDir: "/packs" });
  const answers: Result[] = [
    await geo.reverse({ lat: 48.85, lon: 2.35 }),
    await geo.fromH3("881fb46625fffff"),
    await geo.postal("75001", { country: "FR" }),
    await geo.airport("CDG", { scheme: "iata" }),
    await geo.locode("FRPAR"),
    await geo.phone("+33123456789"),
    await geo.ip("8.8.8.8"),
    await geo.plate("AB-123-CD", { country: "FR" }),
    await geo.geocode("Paris", { country: "FR", prefer: "population" }),
  ];
  for await (const answer of geo.reverseMany([{ lat: 1, lon: 2 }]))
    answers.push(answer);
  const result: Result = await reverse({ lat: 1, lon: 2 });
  // @ts-expect-error detached results are immutable
  result.status = "matched";
  // @ts-expect-error coordinates must be named
  await geo.reverse(1, 2);
  // @ts-expect-error unnamed pairs are not a batch input
  geo.reverseMany([[1, 2]]);
  // @ts-expect-error explicit airport schemes are enumerated
  await geo.airport("CDG", { scheme: "auto" });
  const error: Error = new DataNotInstalledError();
  void error;
  void answers;
  await geo[Symbol.asyncDispose]();
  await using scoped = await Geocoder.open({ dataDir: "/packs" });
  await scoped.reverse({ lat: 1, lon: 2 });
}
void examples;

async function coordinates(geo: Geocoder): Promise<void> {
  const inputs: import("thereabouts").CoordinatePoint[] = [
    { lat: 1, lon: 2 },
    {
      frame: "geodetic",
      lat: 1,
      lon: 2,
      height: 3,
      uncertainty: { hdop: 0.9 },
    },
    { frame: "latlon", lat: 1, lon: 2 },
    { frame: "lla", lat: 1, lon: 2 },
    { frame: "llh", lat: 1, lon: 2 },
    { frame: "ecef", x: 6378137, y: 0, z: 0 },
    { frame: "enu", e: 10, n: 0, u: 0, origin: { lat: 1, lon: 2 } },
    {
      frame: "ned",
      n: 0,
      e: 10,
      d: 0,
      origin: { frame: "ecef", x: 6378137, y: 0, z: 0 },
    },
    { frame: "utm", zone: 31, hemisphere: "N", easting: 500000, northing: 0 },
    { frame: "mgrs", value: "31UDQ4825111932" },
    { frame: "geohash", value: "u09tvw" },
    {
      frame: "pluscode",
      value: "849VCWC8+R9",
      reference: { lat: 37, lon: -122 },
    },
    { frame: "h3", cell: 0x881fb46625fffffn },
    { frame: "s2", cell: "89c25" },
    { frame: "dms", value: "48 51 24.1 N, 2 21 7.9 E" },
    { frame: "nmea", value: "$GPGGA,..." },
    { frame: "geojson", coordinates: [2, 1, 3], type: "Point" },
    { frame: "wkt", value: "POINT (2 1)" },
  ];
  for (const point of inputs) await geo.reversePoint(point, { evidence: true });
  for await (const result of geo.reversePoints(inputs)) {
    if (result.query) {
      // @ts-expect-error nested query provenance is readonly
      result.query.uncertainty.hdop = 1;
      // @ts-expect-error conversion arrays are readonly
      result.query.conversion.push("guessed");
      if (result.query.cell_extent) {
        // @ts-expect-error boundary vertices are readonly
        result.query.cell_extent.boundary[0].lat = 0;
      }
    }
  }
  // @ts-expect-error cell ids must not round through Number
  await geo.reversePoint({ frame: "h3", cell: 612000000000000000 });
  // @ts-expect-error ECEF requires its own component set
  await geo.reversePoint({ frame: "ecef", lat: 1, lon: 2 });
  // @ts-expect-error ENU requires an explicit origin
  await geo.reversePoint({ frame: "enu", e: 1, n: 2, u: 3 });
  // @ts-expect-error ENU cannot take NED components
  await geo.reversePoint({
    frame: "enu",
    n: 1,
    e: 2,
    d: 3,
    origin: { lat: 0, lon: 0 },
  });
  // @ts-expect-error default geodetic input cannot mix in ECEF components
  await geo.reversePoint({ lat: 1, lon: 2, x: 3 });
  // @ts-expect-error an origin cannot mix geodetic and ECEF components
  const wrongOrigin: Origin = { lat: 0, lon: 0, x: 1 };
  void wrongOrigin;
  // @ts-expect-error triples are not guessed
  await geo.reversePoint([1, 2, 3]);
}
void coordinates;
