import io
import json
import sys
from pathlib import Path

import pytest

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.commandline.application import main
from thereabouts.errors import DataNotInstalledError
from thereabouts.packs.jsonio import sha256
from thereabouts.store import data_directory

from .test_api import PACK, ROOT, finest


def test_install_list_verify_and_lookup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["--data-dir", str(tmp_path / "store")]
    assert (
        main(
            [
                *base,
                "data",
                "install",
                "--from",
                str(PACK),
                "--sha256",
                sha256(PACK / "manifest.json"),
                "--offline",
            ]
        )
        == 0
    )
    installed = json.loads(capsys.readouterr().out)
    assert Path(installed["installed"]).is_dir()
    assert main([*base, "data", "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["active"]
    assert main([*base, "data", "verify", "--full"]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] == "full"
    assert main([*base, "reverse", "12.97", "77.59"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["data"]["version"] == "synthetic"
    assert main([*base, "h3", answer["reference"]["h3"]]) == 0
    assert json.loads(capsys.readouterr().out)["selected"] == answer["selected"]
    assert main([*base, "info"]) == 0
    assert json.loads(capsys.readouterr().out)["packs"]["reverse"]["sources"]
    assert main([*base, "explain", "h3", answer["reference"]["h3"]]) == 0
    assert json.loads(capsys.readouterr().out)["raw_evidence_installed"] is False


def test_jsonl_csv_and_collected_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["--pack", str(PACK)]
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '{"latitude":0,"longitude":0}\nbad json\n{"latitude":0,"longitude":180}\n'
        ),
    )
    assert main([*base, "batch", "--errors", "collect", "--chunk-size", "1"]) == 5
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["status"] for r in rows] == [
        "outside_coverage",
        "invalid_input",
        "ineligible",
    ]
    monkeypatch.setattr(sys, "stdin", io.StringIO("lat,lon\n0,0\n91,0\n0,180\n"))
    assert (
        main(
            [
                *base,
                "batch",
                "--format",
                "csv",
                "--latitude-column",
                "lat",
                "--longitude-column",
                "lon",
                "--chunk-size",
                "1",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1 and "latitude" in captured.err
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"key": finest(ROOT)}) + "\n")
    )
    assert main([*base, "batch", "--kind", "h3", "--h3-column", "key"]) == 0
    assert json.loads(capsys.readouterr().out)["query"]["kind"] == "h3"


def test_usage_data_and_installation_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--pack", str(PACK), "reverse", "91", "0"]) == 2
    assert main(["--pack", str(PACK), "resolve", "coordinates", "one"]) == 2
    assert main(["--pack", str(tmp_path / "missing"), "info"]) == 3
    assert (
        main(
            [
                "--data-dir",
                str(tmp_path),
                "data",
                "install",
                "--from",
                str(tmp_path / "missing"),
                "--sha256",
                "0" * 64,
            ]
        )
        == 4
    )
    assert not capsys.readouterr().out
    assert main(["--pack", str(PACK), "resolve", "h3", finest(ROOT)]) == 0
    assert json.loads(capsys.readouterr().out)["query"]["kind"] == "h3"


def test_store_selection_is_explicit_then_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THEREABOUTS_DATA", str(tmp_path / "environment"))
    assert data_directory(tmp_path) == tmp_path
    assert data_directory() == tmp_path / "environment"
    with pytest.raises(DataNotInstalledError):
        Geocoder()
    with Geocoder(PACK) as geo:
        assert geo.info()["packs"]["reverse"]["family"] == "reverse"
    with pytest.raises(InvalidInputError):
        Geocoder(PACK, data_dir=tmp_path)
    monkeypatch.delenv("THEREABOUTS_DATA")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert data_directory() == Path.home() / "Library/Application Support/Thereabouts"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert data_directory() == tmp_path / "xdg/thereabouts"


def test_duplicate_csv_headers_are_invalid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("latitude,longitude,latitude\n1,2,3\n")
    )
    assert (
        main(["--pack", str(PACK), "batch", "--format", "csv", "--errors", "collect"])
        == 5
    )
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_input"


def test_broken_pipe_has_no_traceback() -> None:
    import subprocess

    root = Path(__file__).parents[2]
    command = [
        sys.executable,
        "-m",
        "thereabouts.commandline.application",
        "--pack",
        str(PACK),
        "batch",
    ]
    with subprocess.Popen(
        command,
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        assert process.stdin and process.stdout and process.stderr
        process.stdin.write(b'{"latitude":12.97,"longitude":77.59}\n' * 100)
        process.stdin.close()
        assert process.stdout.readline()
        process.stdout.close()
        assert process.wait(timeout=10) == 0
        assert not process.stderr.read()
