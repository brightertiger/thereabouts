"""Assemble source coordinates and freeze split before any grading."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
rows = list(csv.DictReader((ROOT / "candidates.tsv").open(), delimiter="\t"))
overrides = {
    r["id"]: r
    for r in csv.DictReader((ROOT / "coordinate_overrides.tsv").open(), delimiter="\t")
}
out = []
for row in rows:
    r = dict(row)
    if r["id"] in overrides:
        r.update({k: v for k, v in overrides[r["id"]].items() if k != "id"})
    else:
        source = json.loads(
            (ROOT / "sources" / (r["id"] + "-wikipedia.json")).read_text()
        )
        r["latitude"], r["longitude"] = [v.strip() for v in source["geo"][0].split(";")]
        r["coordinate_source"] = source["url"]
        r["note"] = "Wikipedia landmark coordinate; independently map-checked."
    n = int(r["id"].rsplit("-", 1)[1])
    is_dev = (
        (r["group"] == "large-city" and n in (3, 6))
        or (
            r["group"] == "neighbour"
            and (n == 1 or r["id"] in ("howrah-04", "yokohama-04"))
        )
        or (r["group"] == "town" and n == 1)
        or r["id"] in ("castle-combe-01", "mawlynnong-01", "nieu-bethesda-01")
    )
    r["split"] = "dev" if is_dev else "holdout"
    out.append(r)
with (ROOT / "coordinates.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)
print(
    "Prepared",
    len(out),
    "coordinates; dev",
    sum(r["split"] == "dev" for r in out),
    "holdout",
    sum(r["split"] == "holdout" for r in out),
)
