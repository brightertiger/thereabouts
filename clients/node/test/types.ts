import { Geocoder, reverse, Result, DataNotInstalledError } from "thereabouts";
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
