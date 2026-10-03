import shutil
from pathlib import Path

import pytest

from thereabouts.client import Geocoder
from thereabouts.client_errors import IncompatibleDataError
from thereabouts.commandline.application import main
from thereabouts.installing.install import install
from thereabouts.packs.jsonio import canonical, digest, parse, sha256
from thereabouts.store import installed_pack, list_packs


def test_install_optional_families_without_reverse_and_cli(
    code_packs: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for family in ("postal", "airports"):
        source = code_packs[family]
        installed = install(
            source,
            manifest_sha256=sha256(source / "manifest.json"),
            data_dir=tmp_path,
            offline=True,
        )
        assert installed_pack(tmp_path, family=family) == installed
        assert (
            main(
                [
                    "--data-dir",
                    str(tmp_path),
                    "data",
                    "verify",
                    "--family",
                    family,
                    "--full",
                ]
            )
            == 0
        )
    assert {row["family"] for row in list_packs(tmp_path) if row["active"]} == {
        "postal",
        "airports",
    }
    with Geocoder(data_dir=tmp_path, packs=["postal", "airports"]) as geo:
        assert geo.postal("00100", country="AA").status == "matched"
        assert geo.airport("ZZZ", scheme="iata").status == "ambiguous"
    capsys.readouterr()
    assert (
        main(["--data-dir", str(tmp_path), "postal", "00100", "--country", "AA"]) == 0
    )
    assert parse(capsys.readouterr().out)["status"] == "matched"
    assert (
        main(
            [
                "--data-dir",
                str(tmp_path),
                "resolve",
                "airport",
                "ZZZ",
                "--scheme",
                "iata",
            ]
        )
        == 0
    )
    assert parse(capsys.readouterr().out)["selected"] is None
    assert (
        main(
            [
                "--data-dir",
                str(tmp_path),
                "explain",
                "postal",
                "00100",
                "--country",
                "AA",
            ]
        )
        == 0
    )
    assert parse(capsys.readouterr().out)["result"]["selected"]["observations"]


def test_multi_pack_compatibility_and_explicit_family(
    code_packs: dict[str, Path], tmp_path: Path
) -> None:
    with Geocoder(packs=code_packs) as geo:
        assert (
            geo.reverse(12.97, 77.59).data.manifest_sha256
            != geo.postal("00100", country="AA").data.manifest_sha256
        )
        assert set(geo.info()["packs"]) == {"reverse", "postal", "airports"}
    bad = tmp_path / "postal"
    shutil.copytree(code_packs["postal"], bad)
    value = parse((bad / "manifest.json").read_bytes())
    value["catalogue_epoch"] = value["export"]["release"]["catalogue_epoch"] = (
        "different"
    )
    value["export_fingerprint"] = digest(value["export"])
    (bad / "manifest.json").write_bytes(canonical(value))
    with pytest.raises(IncompatibleDataError, match="epoch"):
        Geocoder(packs={"reverse": code_packs["reverse"], "postal": bad})
    with pytest.raises(IncompatibleDataError, match="family"):
        Geocoder(packs={"postal": code_packs["airports"]})
