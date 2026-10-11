"""Read identifiers from public Wikimedia pages, never project datasets."""

import csv
import json
from concurrent.futures import ThreadPoolExecutor

from research import ROOT, get, wiki


def entity(qid):
    path = ROOT / "sources" / (qid + "-wikidata.json")
    if path.exists():
        return json.loads(path.read_text())
    url = "https://www.wikidata.org/wiki/Special:EntityData/" + qid + ".json"
    result = {"url": url, "checked": "2026-10-02", "qid": qid}
    try:
        data = json.loads(get(url))["entities"][qid]
        result["label"] = data.get("labels", {}).get("en", {}).get("value", "")
        result["description"] = (
            data.get("descriptions", {}).get("en", {}).get("value", "")
        )
        result["revision"] = data.get("lastrevid")
        result["aliases"] = {
            k: v
            for k, v in data.get("aliases", {}).items()
            if k
            in [
                "en",
                "bn",
                "hi",
                "mr",
                "zh",
                "ja",
                "ms",
                "fr",
                "pt",
                "de",
                "is",
                "es",
                "az",
            ]
        }
        result["claims"] = {
            k: data.get("claims", {}).get(k, [])
            for k in ["P625", "P17", "P1566", "P1082", "P1448"]
        }
    except Exception as exc:
        result["error"] = str(exc)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    rows = list(csv.DictReader((ROOT / "candidates.tsv").open(), delimiter="\t"))
    city_pages = {
        "New York": "New York City",
        "Oak Park": "Oak Park, Illinois",
        "Evanston": "Evanston, Illinois",
        "Wilmette": "Wilmette, Illinois",
        "Takayama": "Takayama, Gifu",
        "Vik": "Vík í Mýrdal",
        "Monsanto": "Monsanto (Idanha-a-Nova)",
        "Ogimachi": "Ogimachi, Shirakawa",
        "Hogsback": "Hogsback, Eastern Cape",
        "New Norcia": "New Norcia, Western Australia",
        "Nundle": "Nundle, New South Wales",
        "Terlingua": "Terlingua, Texas",
        "Cachora": "San Pedro de Cachora",
    }
    places = {}
    for row in rows:
        places[row["expected_name"]] = {
            "id": "place-" + row["id"].rsplit("-", 1)[0],
            "page": city_pages.get(row["expected_name"], row["expected_name"]),
        }
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name, result in zip(places, pool.map(wiki, places.values()), strict=False):
            places[name].update(result)
    (ROOT / "sources" / "place-identifiers.json").write_text(
        json.dumps(places, ensure_ascii=False, indent=2) + "\n"
    )
    qids = set()
    for path in (ROOT / "sources").glob("*-wikipedia.json"):
        qids.update(json.loads(path.read_text()).get("qid", []))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(entity, sorted(qids)):
            coords = [
                x["mainsnak"].get("datavalue", {}).get("value")
                for x in result.get("claims", {}).get("P625", [])
            ]
            print(
                result["qid"],
                result.get("label"),
                coords,
                result.get("error", ""),
                flush=True,
            )
