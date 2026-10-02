"""Cache short primary-source excerpts and map links for manual review."""

import csv
import html
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from research import ROOT, UA

points = {
    r["id"]: r for r in csv.DictReader((ROOT / "candidates.tsv").open(), delimiter="\t")
}


def check(row):
    p = ROOT / "sources" / (row["id"] + "-primary.json")
    if p.exists():
        cached = json.loads(p.read_text())
        if cached["url"] == row["url"]:
            return cached
    r = dict(row, checked="2026-10-02")
    try:
        with urllib.request.urlopen(
            urllib.request.Request(row["url"], headers={"User-Agent": UA}), timeout=25
        ) as response:
            r["status"] = response.status
            r["resolved_url"] = response.url
            content = response.read()
            if content.startswith(b"%PDF"):
                r["format"] = "pdf"
                r["note"] = (
                    "Read through browser research search excerpts; HTTP availability verified."
                )
            else:
                body = content.decode("utf8", errors="replace")
                r["map_links"] = list(
                    dict.fromkeys(
                        html.unescape(x)
                        for x in re.findall(r"(?:src|href)=[\"\']([^\"\']+)", body)
                        if any(
                            t in x
                            for t in [
                                "maps.google",
                                "google.com/maps",
                                "goo.gl/maps",
                                "maps.app",
                                "openstreetmap",
                                "geohack",
                            ]
                        )
                    )
                )[:10]
                body = re.sub(
                    r"<(script|style)\b[^>]*>.*?</\1>", " ", body, flags=re.S | re.I
                )
                text = re.sub(
                    r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))
                ).strip()
                # First 100 words plus up to 80 around the last city mention:
                # short evidence excerpts, not mirrors of copyrighted pages.
                r["lead"] = " ".join(text.split()[:100])
                name = points[row["id"]]["expected_name"]
                pos = text.lower().rfind(name.lower())
                r["place_context"] = (
                    " ".join(text[max(0, pos - 200) : pos + 700].split()[:80])
                    if pos >= 0
                    else ""
                )
    except Exception as e:
        r["error"] = str(e)
    p.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n")
    return r


if __name__ == "__main__":
    rows = list(csv.DictReader((ROOT / "primary_sources.tsv").open(), delimiter="\t"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for r in pool.map(check, rows):
            print(r["id"], r.get("status", ""), r.get("error", ""), flush=True)
