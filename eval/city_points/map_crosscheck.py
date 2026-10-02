"""One-off cached Nominatim cross-check; not a project evaluator.

Policy: https://operations.osmfoundation.org/policies/nominatim/
One process/thread/machine, >=1.1 seconds between completed requests,
descriptive User-Agent, cache every response, hard cap of 149 requests.
No automatic retries. Does not derive or change expected city answers.
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "sources"
UA = "CityPointsReference/1.0 (one-off 120-point public-source QA cross-check; cached; maximum 149 requests)"


def request(key, endpoint, params):
    path = CACHE / ("nominatim-" + key + ".json")
    params = dict(
        params, format="jsonv2", addressdetails="1", **{"accept-language": "en"}
    )
    url = (
        "https://nominatim.openstreetmap.org/"
        + endpoint
        + "?"
        + urllib.parse.urlencode(params)
    )
    if path.exists():
        cached = json.loads(path.read_text())
        if cached["url"] != url:
            raise RuntimeError(
                "Cached request differs; retain the cache and use a new review key"
            )
        return cached
    count = len(list(CACHE.glob("nominatim-*.json")))
    if count >= 149:
        raise RuntimeError("Nominatim one-off request limit reached")
    result = {"url": url, "checked": "2026-10-02"}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30
        ) as response:
            result["result"] = json.load(response)
    except Exception as exc:
        result["error"] = str(exc)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    time.sleep(1.1)
    return result


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "search":
        with (ROOT / "map_queries.tsv").open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                r = request(
                    "search-" + row["id"],
                    "search",
                    {
                        "q": row["query"],
                        "limit": 2,
                        "countrycodes": row["country_code"].lower(),
                    },
                )
                print(
                    row["id"],
                    [
                        (v["lat"], v["lon"], v["display_name"])
                        for v in r.get("result", [])
                    ],
                    r.get("error", ""),
                    flush=True,
                )
    elif mode == "reverse":
        with (ROOT / "coordinates.csv").open() as f:
            for row in csv.DictReader(f):
                r = request(
                    "reverse-" + row["id"],
                    "reverse",
                    {"lat": row["latitude"], "lon": row["longitude"], "zoom": 18},
                )
                v = r.get("result", {})
                print(
                    row["id"],
                    v.get("name", ""),
                    v.get("display_name", ""),
                    r.get("error", ""),
                    flush=True,
                )
