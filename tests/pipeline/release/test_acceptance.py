"""Packs are opened by the real reader at 256 files and checked against the dataset."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.config.release import AcceptanceSettings
from pipeline.release import acceptance, client, samples
from pipeline.release.samples import Query

from .synthetic import dataset as synthetic_dataset

FAMILIES = ("core", "postal", "airports", "locode", "phone", "ip", "plates")


@pytest.fixture(scope="module")
def release(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("acceptance")
    dataset, _ = synthetic_dataset(root)
    writer = client.binding()
    for family in FAMILIES:
        client.write(dataset, family, root / "packs" / family, "2026.10", writer)
    return root


@pytest.fixture
def settings() -> AcceptanceSettings:
    return replace(load().release.acceptance, ocean_points=40)


def accept(release: Path, family: str, settings: AcceptanceSettings) -> Path:
    return acceptance.accept(
        release / "dataset/2026.10", release / "packs", family, "2026.10", settings
    )


def test_every_family_passes_with_a_stable_report(
    release: Path, settings: AcceptanceSettings
) -> None:
    logged: list[str] = []
    for family in FAMILIES:
        path = acceptance.accept(
            release / "dataset/2026.10",
            release / "packs",
            family,
            "2026.10",
            settings,
            logged.append,
        )
        report = json.loads(path.read_text())
        assert report["passed"] and report["pack"]["verified"]
        assert report["open_files"] == 256
        assert all(
            check["agreed"] == check["applicable"]
            for check in report["checks"].values()
        )
        assert report["checks"]["vectors"]["applicable"] > 0
        before = path.read_bytes()
        assert accept(release, family, settings).read_bytes() == before
    core = json.loads((release / "packs/acceptance/core.json").read_text())
    assert set(core["checks"]) == {
        "reverse",
        "ocean",
        "names",
        "alternate_names",
        "vectors",
    }
    assert core["checks"]["ocean"]["agreed"] == 40
    assert all("at ulimit -n 256" in line for line in logged)


def break_one(check: str, monkeypatch: pytest.MonkeyPatch) -> None:
    original = samples.queries

    def wrong(*args: object) -> list[Query]:
        found = original(*args)  # type: ignore[arg-type]
        number = next(i for i, q in enumerate(found) if q.check == check)
        found[number] = replace(
            found[number], expect={**found[number].expect, "city_id": "city:wrong"}
        )
        return found

    monkeypatch.setattr(samples, "queries", wrong)


def test_a_disagreement_blocks_and_keeps_a_failure_report(
    release: Path, settings: AcceptanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = release / "packs/acceptance/postal.json"
    target.unlink(missing_ok=True)
    break_one("postal", monkeypatch)
    with pytest.raises(ValueError, match=r"failed for 2026\.10/postal: \['postal'\]"):
        accept(release, "postal", settings)
    assert not target.exists()
    failed = json.loads((release / "packs/acceptance/postal.failed.json").read_text())
    (failure,) = failed["checks"]["postal"]["failures"]
    assert failure["expect"]["city_id"] == "city:wrong"
    assert failure["answer"]["status"] == "matched"


def test_a_configured_share_admits_known_disagreement(
    release: Path, settings: AcceptanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    break_one("reverse", monkeypatch)
    lenient = replace(settings, minimum={**settings.minimum, "reverse": 0.5})
    report = json.loads(accept(release, "core", lenient).read_text())
    check = report["checks"]["reverse"]
    assert check["agreed"] == check["applicable"] - 1 and check["passed"]
    assert not (release / "packs/acceptance/core.failed.json").exists()


def test_a_pack_the_reader_cannot_open_fails(
    release: Path, settings: AcceptanceSettings, tmp_path: Path
) -> None:
    packs = tmp_path / "packs"
    shutil.copytree(release / "packs/ip", packs / "ip")
    shutil.copytree(release / "packs/core", packs / "core")
    shard = next(path for path in (packs / "ip").iterdir() if path.suffix == ".bin")
    shard.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Pack probe failed at ulimit -n 256"):
        acceptance.accept(release / "dataset/2026.10", packs, "ip", "2026.10", settings)
