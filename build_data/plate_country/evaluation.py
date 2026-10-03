"""Reproducible source-transcription benchmark with plate-level held-out groups."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from build_data.acquire.io import sha256_file, write_json
from build_data.acquire.plates_html import Document

from .policy import Row, code_key, policy
from .resolver import Resolver
from .sources import pins, source_fields


def examples(data: Path) -> list[Row]:
    sources = pins(data)
    rows = []
    seen = set()
    for rule in policy("evaluation"):
        pin = sources[rule["source"]]
        raw = json.loads(Path(pin["path"]).read_text(encoding="utf-8"))
        page = raw["query"]["pages"][str(rule["page_id"])]
        info = page["imageinfo"][0]
        if rule["method"] == "visual_transcription":
            pin_image = sources[rule["image_source"]]
            if pin_image["sha256"] != rule["annotation_source_sha256"]:
                raise ValueError("Image annotation refers to different source bytes")
            image_bytes = Path(pin_image["path"]).read_bytes()
            if hashlib.sha1(image_bytes).hexdigest() != info["sha1"]:
                raise ValueError("Image no longer matches Commons metadata")
            plate = policy("image_transcriptions")[rule["annotation"]]
        else:
            field = (
                page["title"]
                if rule["field"] == "title"
                else Document(info["extmetadata"]["ImageDescription"]["value"]).text
            )
            match = re.search(rule["pattern"], field)
            if match is None:
                raise ValueError(f"Missing evaluation transcription: {rule}")
            plate = match["plate"] if "plate" in match.groupdict() else match[0]
        identity = rule["country_code"] + ":" + code_key(plate)
        if identity in seen:
            continue
        seen.add(identity)
        group = hashlib.sha256(identity.encode()).hexdigest()
        rows.append(
            dict(
                rule,
                plate=plate,
                split="holdout" if int(group[:8], 16) % 5 == 0 else "development",
                group=group,
                provenance=source_fields(pin),
                image_url=info["url"],
                image_source_sha256=(
                    sources[rule["image_source"]]["sha256"]
                    if "image_source" in rule
                    else None
                ),
                image_sha1=info["sha1"],
                image_license=info["extmetadata"]["LicenseShortName"]["value"],
                image_license_url=info["extmetadata"]
                .get("LicenseUrl", {})
                .get("value"),
                image_attribution=info["extmetadata"].get("Artist", {}).get("value"),
                page_revision=page["revisions"][0]["revid"],
            )
        )
    return rows


def metrics(rows: list[Row]) -> Row:
    count = len(rows)
    return dict(
        n=count,
        countries=len({r["country_code"] for r in rows}),
        top1=sum(r["top1"] for r in rows) / count if count else None,
        top3=sum(r["top3"] for r in rows) / count if count else None,
        candidate_recall=sum(r["truth_in_candidates"] for r in rows) / count
        if count
        else None,
        hint_levels=dict(Counter(r["hint_level"] for r in rows)),
        hint_reasons=dict(Counter(r["hint_reason"] for r in rows)),
    )


def evaluate(data: Path) -> Row:
    root = data / "normalized" / "plates_country"
    resolver = Resolver.load(root)
    groups: dict[str, list[Row]] = defaultdict(list)
    results = []
    for example in examples(data):
        plate, country = example["plate"], example["country_code"]
        inferred = resolver.resolve(plate)
        candidates = [r["country_code"] for r in inferred["candidates"]]
        hinted = resolver.resolve(plate, country)
        region = resolver.countries[country]["region"]
        row = dict(
            example,
            region=region,
            candidates=candidates,
            top1=country in candidates[:1],
            top3=country in candidates[:3],
            truth_in_candidates=country in candidates,
            hint_level=hinted["level"],
            hint_reason=hinted["reason"],
        )
        results.append(row)
        for group in (
            "all",
            example["split"],
            "all/" + region,
            example["split"] + "/" + region,
            "method/" + example["method"],
            "kind/" + example.get("example_kind", "documented_caption"),
        ):
            groups[group].append(row)
    report = dict(
        version=1,
        manifest_sha256=sha256_file(root / "manifest.json"),
        evaluation_policies={
            name: sha256_file(Path(__file__).with_name("data") / (name + ".json"))
            for name in ("evaluation", "image_transcriptions")
        },
        split="sha256(country + ':' + normalized_code)[0:8] mod 5 == 0 is holdout",
        metrics={key: metrics(rows) for key, rows in sorted(groups.items())},
        rows=results,
        limitations=[
            "Convenience sample of documented plates; not a road-frequency estimate.",
            "Files whose names appeared in format articles were excluded; "
            "this is not proof of publisher independence.",
            "Country labels and image transcriptions reviewed by Codex; "
            "no independent human audit. Not an OCR benchmark.",
            "Weights and benchmark-country formats frozen in 9aa2f29 before labels. "
            "Later gap-country rules add only countries absent from this sample.",
            "An alternation-preservation compiler fix after the first run "
            "corrected one holdout example; source patterns/weights unchanged.",
            "Geographic levels measure availability, not verified place accuracy.",
        ],
    )
    write_json(root / "evaluation.json", report)
    return report
