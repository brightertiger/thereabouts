import { Geocoder, type Resolution, requireOne } from "thereabouts";
async function example(): Promise<Resolution> {
  const geo = await Geocoder.open({
    packs: { postal: "postal", reverse: "reverse" },
  });
  const result = await geo.postal("00100", { country: "AA" });
  const city: string | undefined = requireOne(result)?.city?.name;
  void city;
  for await (const row of geo.reverseMany([[12, 77]])) {
    const status: Resolution["status"] = row.status;
    void status;
  }
  // @ts-expect-error an airport scheme is required
  await geo.airport("ZZZ", {});
  // @ts-expect-error results are immutable
  result.candidates.push(result.selected);
  await geo.close();
  return result;
}
void example;
