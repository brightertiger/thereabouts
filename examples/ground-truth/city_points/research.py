"""One-off evidence collection. Does not import or query the geocoder.

All output is restricted to this directory. Nominatim is deliberately not
part of this script; its optional cross-check is separately rate limited.
"""

import csv
import html
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "CityPointsReference/1.0 (one-off public-source reference research)"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read().decode("utf-8")


def wiki(row):
    path = ROOT / "sources" / (row["id"] + "-wikipedia.json")
    if path.exists():
        return json.loads(path.read_text())
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
        row["page"].replace(" ", "_")
    )
    result = {"id": row["id"], "url": url, "checked": "2026-10-02"}
    try:
        body = get(url)
        result["geo"] = re.findall(r'<span class="geo">(.*?)</span>', body)
        result["decimal"] = re.findall(
            r'<span class="(?:latitude|longitude)">(.*?)</span>', body
        )[:2]
        result["qid"] = re.findall(r'"wgWikibaseItemId":"(Q\d+)"', body)
        if not result["qid"]:
            result["qid"] = re.findall(r"https://www.wikidata.org/wiki/(Q\d+)", body)[
                :1
            ]
        result["map_coordinates"] = re.findall(r'params=([^&"\s<>]+)', body)[:3]
        # Retain the infobox and lead as short machine-readable evidence.
        clean = re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=re.S)
        match = re.search(r'<table\b[^>]*class="[^\"]*infobox', clean)
        if match:
            clean = clean[match.start() :]
        clean = re.sub(r"<[^>]+>", " ", clean)
        result["excerpt"] = re.sub(r"\s+", " ", html.unescape(clean))[:16000]
        result["external_urls"] = list(
            dict.fromkeys(
                html.unescape(x)
                for x in re.findall(r'href="(https?://[^"<>]+)"', body)
                if "wikipedia" not in x
                and "wikimedia" not in x
                and "wikidata" not in x
                and "geohack" not in x
            )
        )
    except Exception as exc:
        result["error"] = str(exc)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    rows = list(csv.DictReader((ROOT / "candidates.tsv").open(), delimiter="\t"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for r in pool.map(wiki, rows):
            print(
                r["id"],
                r.get("geo", []),
                r.get("qid", []),
                r.get("error", ""),
                flush=True,
            )
