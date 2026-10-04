"""Forward geography resolves only through the explicitly pinned core catalogue."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from thereabouts import Geocoder, IncompatibleDataError, _core

FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_standalone_and_attached_core() -> None:
    postal = FIXTURES / "packs/postal-synthetic"
    with Geocoder(postal) as geo:
        bare = geo.postal("00100", country="AA")
    with Geocoder(
        packs={"core": FIXTURES / "packs/core-synthetic", "postal": postal}
    ) as geo:
        enriched = geo.postal("00100", country="AA")
    assert bare.status == enriched.status == "matched"
    assert bare.country == enriched.country
    # Legacy forward fixture has no subdivision code to retain without core.
    assert bare.state is not None and enriched.state is not None
    assert bare.state.name == enriched.state.name
    assert bare.state.code is None and enriched.state.code == "AA.A"
    assert bare.point == enriched.point
    assert bare.city is None and bare.timezone is None
    assert enriched.city is not None
    assert enriched.timezone == "Fixture/One"


def test_same_release_wrong_catalogue_is_rejected() -> None:
    with (
        Geocoder(
            packs={
                "core": FIXTURES / "packs/core-names-synthetic",
                "postal": FIXTURES / "packs/postal-synthetic",
            }
        ) as geo,
        pytest.raises(IncompatibleDataError, match="catalogue identity"),
    ):
        geo.postal("00100", country="AA")


def test_forward_manifest_requires_pin_and_has_no_catalogue(tmp_path: Path) -> None:
    source = FIXTURES / "packs/postal-synthetic"
    info = _core.pack_info(str(source))
    core = _core.pack_info(str(FIXTURES / "packs/core-synthetic"))
    inventory = [
        [f["path"], f["size"], f["sha256"]]
        for f in core["files"]
        if f["kind"] == "catalogue"
    ]
    digest = hashlib.sha256(
        json.dumps(inventory, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert info["core_catalogue"]["sha256"] == digest
    assert info["format_minor"] == 2
    assert info["storage"]["catalogue_bytes"] == 0
    assert not any(f["kind"] == "catalogue" for f in info["files"])
    shutil.copytree(source, tmp_path / "pack")
    info.pop("core_catalogue")
    (tmp_path / "pack/manifest.json").write_text(json.dumps(info))
    with pytest.raises(IncompatibleDataError, match=r"2\.2"):
        _core.open(str(tmp_path / "pack"))
