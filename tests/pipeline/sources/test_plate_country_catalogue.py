"""The plate-country proposal names exactly the documents the plates pin lacks."""

from collections import defaultdict

import yaml

from pipeline.config import load
from pipeline.engines.plate_country.policy import base_policy, policy
from pipeline.pins.lock import read_lock
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.sources.proposals.catalog import load as catalogue


def test_catalogue_covers_unpinned_rules_priors_and_the_benchmark() -> None:
    settings = load().sources["plate_country"]
    files = {item.name: item for item in catalogue(settings).files}
    plates = {item.name for item in read_lock(REPOSITORY / "pins.lock")["plates"].files}
    rules = [r for rows in base_policy("formats").values() for r in rows] + [
        r
        for name in ("formats", "supplemental_formats", "templates", "state_tables")
        for r in policy(name)
    ]
    needed = ({"vehicle-stock.json"} | {r["source"] for r in rules}) - plates
    assert needed == {name for name in files if not name.startswith("eval-")}
    assert len(needed) == 25
    for name in needed:
        item = files[name]
        assert f"oldid={item.metadata['revision']}" in item.url
        assert item.metadata["kind"] == "wikipedia"
    evaluation = yaml.safe_load(
        (REPOSITORY / "eval/plate_country/evaluation.yaml").read_text()
    )
    pages: dict[str, set[str]] = defaultdict(set)
    for rule in evaluation:
        pages[rule["source"]].add(str(rule["page_id"]))
    images = {r["image_source"] for r in evaluation if "image_source" in r}
    assert set(pages) | images == {n for n in files if n.startswith("eval-")}
    for name, ids in pages.items():
        selected = files[name].url.split("pageids=", 1)[1].split("&", 1)[0]
        assert set(selected.split("%7C")) == ids
    for name, item in files.items():
        assert item.metadata["key"] == name and item.metadata["license"]
        if item.url.startswith("https://upload.wikimedia.org/"):
            assert "?" not in item.url


def test_plate_country_settings_name_the_real_publishers() -> None:
    settings = load().sources["plate_country"]
    assert "worldlicenseplates" not in str(settings.upstream) + str(settings.licence)
    reviewed = yaml.safe_load(
        (REPOSITORY / "config/policies/plate_country/sources.yaml").read_text()
    )
    sizes = sum(reviewed[item.name]["size"] for item in catalogue(settings).files)
    assert settings.limits.download_bytes >= 2 * sizes
