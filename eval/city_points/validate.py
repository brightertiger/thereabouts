"""Offline integrity and cached-coordinate audit; never runs the project lookup."""

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
FIELDS = [
    "id",
    "group",
    "role",
    "latitude",
    "longitude",
    "expected_name",
    "accepted_names",
    "expected_kind",
    "country_code",
    "expected_wikidata",
    "expected_geonames_id",
    "what_is_here",
    "source_url",
    "source_checked",
    "reason",
    "confidence",
    "ambiguous",
    "split",
]
COUNTS = {
    "large-city": (60, 20, 40),
    "neighbour": (24, 8, 16),
    "town": (18, 9, 9),
    "rural": (18, 3, 15),
}
COUNTRIES = {
    "AR",
    "AU",
    "AZ",
    "BD",
    "BR",
    "CN",
    "FR",
    "GB",
    "IN",
    "IS",
    "JP",
    "MY",
    "NA",
    "NO",
    "NZ",
    "PE",
    "PT",
    "TR",
    "US",
    "ZA",
}


def haversine(lat1, lon1, lat2, lon2):
    a, b, c, d = map(math.radians, (lat1, lon1, lat2, lon2))
    h = (
        math.sin((c - a) / 2) ** 2
        + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    )
    return 12742000 * math.asin(min(1, math.sqrt(h)))


def main():
    with (ROOT / "points.csv").open(encoding="utf8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == FIELDS, "Unexpected CSV columns"
        rows = list(reader)
    evidence_rows = list(csv.DictReader((ROOT / "evidence.csv").open(encoding="utf8")))
    evidence = {r["id"]: r for r in evidence_rows}
    assert len(rows) == len(evidence_rows) == len(evidence) == 120
    assert all(None not in r and all(v is not None for v in r.values()) for r in rows)
    assert len({r["id"] for r in rows}) == 120, "Duplicate IDs"
    assert len({(r["latitude"], r["longitude"]) for r in rows}) == 120, (
        "Duplicate coordinates"
    )
    assert set(evidence) == {r["id"] for r in rows}
    assert {r["country_code"] for r in rows} == COUNTRIES
    by_place = defaultdict(list)
    distances = {}
    for r in rows:
        key = r["id"]
        assert re.fullmatch(r"[a-z]+(?:-[a-z]+)*-\d{2}", key), key
        assert r["group"] in COUNTS and r["split"] in {"dev", "holdout"}, key
        assert r["role"] in {"centre", "interior", "edge", "facing-side"}, key
        assert r["confidence"] in {"high", "medium"} and r["ambiguous"] in {
            "yes",
            "no",
        }, key
        assert r["expected_kind"] in {"city", "town", "village"}, key
        assert r["source_checked"] == "2026-10-02", key
        for name in ("expected_name", "what_is_here", "reason"):
            assert r[name].strip(), (key, name)
        assert not r["expected_wikidata"] or re.fullmatch(
            r"Q[1-9]\d*", r["expected_wikidata"]
        ), key
        assert not r["expected_geonames_id"] or re.fullmatch(
            r"[1-9]\d*", r["expected_geonames_id"]
        ), key
        aliases = r["accepted_names"].split("|") if r["accepted_names"] else []
        assert all(a.strip() == a and a for a in aliases), key
        assert (
            len(aliases) == len(set(aliases)) and r["expected_name"] not in aliases
        ), key
        urls = r["source_url"].split("|")
        assert len(set(urls)) >= 2, key
        assert all(
            urlsplit(u).scheme in {"http", "https"} and urlsplit(u).netloc for u in urls
        ), key
        lat, lon = float(r["latitude"]), float(r["longitude"])
        assert (
            math.isfinite(lat)
            and math.isfinite(lon)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ), key
        e = evidence[key]
        assert e["membership_source"] == urls[0] and e["map_source"] in urls, key
        assert e["osm_only"] == "no" and int(e["non_osm_source_families"]) >= 1, key
        cache_path = (ROOT / e["map_cache"]).resolve()
        assert cache_path.is_relative_to(ROOT / "sources"), key
        cache = json.loads(cache_path.read_text())
        query = parse_qs(urlsplit(cache["url"]).query)
        assert abs(float(query["lat"][0]) - lat) <= 0.00000051, (
            key,
            "stale map latitude",
        )
        assert abs(float(query["lon"][0]) - lon) <= 0.00000051, (
            key,
            "stale map longitude",
        )
        v = cache["result"]
        assert (
            v["address"]["country_code"].upper()
            == e["map_country"]
            == r["country_code"]
        ), key
        distances[key] = round(haversine(lat, lon, float(v["lat"]), float(v["lon"])), 2)
        assert distances[key] < 500, (
            key,
            "Map matched a remote feature",
            distances[key],
        )
        by_place[r["expected_name"]].append(r)

    count_report = {}
    readme = (ROOT / "README.md").read_text()
    for group, (total, dev, holdout) in COUNTS.items():
        selected = [r for r in rows if r["group"] == group]
        counts = Counter(r["split"] for r in selected)
        assert len(selected) == total and counts == {"dev": dev, "holdout": holdout}, (
            group
        )
        assert f"| {group} | {total} | {dev} | {holdout} |" in readme, group
        count_report[group] = {"total": total, "dev": dev, "holdout": holdout}
    assert Counter(r["split"] for r in rows) == {"dev": 40, "holdout": 80}
    for name, selected in by_place.items():
        group = selected[0]["group"]
        if group != "rural":
            assert {r["split"] for r in selected} == {"dev", "holdout"}, name
        roles = Counter(r["role"] for r in selected)
        if group == "large-city":
            assert roles == {"centre": 1, "interior": 3, "edge": 2}, name
        elif group == "neighbour":
            assert roles == {"centre": 1, "interior": 2, "facing-side": 1}, name
        elif group == "town":
            assert len(selected) == 2, name
        else:
            assert len(selected) == 1, name
    required = {
        "Delhi": "New Delhi",
        "London": "Westminster",
        "Tokyo": "Shinjuku",
        "New York": "Brooklyn",
        "Istanbul": "Asian side",
    }
    for place, unit in required.items():
        assert any(
            r["role"] == "interior" and unit in r["what_is_here"]
            for r in by_place[place]
        ), place
    single_non_osm = sorted(
        e["id"] for e in evidence_rows if e["non_osm_source_families"] == "1"
    )
    ambiguous = [r["id"] for r in rows if r["ambiguous"] == "yes"]
    assert ambiguous == ["bario-01"]
    assert len(single_non_osm) == 21 and "21 rows" in readme
    assert Counter(r["confidence"] for r in rows) == {"high": 90, "medium": 30}
    requests = len(list((ROOT / "sources").glob("nominatim-*.json")))
    assert requests == 148 and "148 requests" in readme
    report = {
        "checked": "2026-10-02",
        "status": "passed",
        "scope": "CSV integrity, documented strata, cached country and nearby-feature checks; no boundary polygon or project accuracy test",
        "rows": len(rows),
        "counts": count_report,
        "split": {"dev": 40, "holdout": 80},
        "country_count": len(COUNTRIES),
        "expected_place_count": len(by_place),
        "confidence": dict(Counter(r["confidence"] for r in rows)),
        "duplicate_ids": 0,
        "duplicate_coordinates": 0,
        "cached_country_checks_passed": 120,
        "nearby_map_feature_distance_m": distances,
        "largest_nearby_map_feature_distance_m": max(distances.values()),
        "single_non_osm_source_family_rows": single_non_osm,
        "osm_only_rows": [],
        "ambiguous_rows": ambiguous,
        "wikidata_present": sum(bool(r["expected_wikidata"]) for r in rows),
        "geonames_id_present": sum(bool(r["expected_geonames_id"]) for r in rows),
        "nominatim_requests_including_rejected_candidates": requests,
        "project_predictions_examined": 0,
        "formal_boundary_buffers_verified": False,
        "points_sha256": hashlib.sha256((ROOT / "points.csv").read_bytes()).hexdigest(),
        "split_sha256": hashlib.sha256(
            "".join(r["id"] + "," + r["split"] + "\n" for r in rows).encode()
        ).hexdigest(),
    }
    (ROOT / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "nearby_map_feature_distance_m"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
