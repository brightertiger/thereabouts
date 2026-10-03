"""Every committed current vector is executed by the actual console script."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conformance.forward_legacy import resolve
from tests.conformance.pack_selection import selection
from thereabouts import Geocoder, _core

from .helpers import FIXTURES, console, install_fixture

BUNDLES = [
    "core-sample",
    "postal",
    "airports",
    "locode",
    "phone",
    "ip",
    "plates",
    "geocode",
]
# The grammar rejects these invalid option values before invoking the core.
USAGE_CASES = {
    "postal-022",
    "airports-027",
    "core-names-sample-034",
    "core-names-sample-035",
    "core-names-sample-036",
    "core-names-sample-037",
}


def arguments(request: dict[str, Any]) -> list[str]:
    kind = request["kind"]
    if kind == "coordinates":
        lat, lon = request["values"]
        return ["reverse", "--lat", str(lat), "--lon", str(lon)]
    args = [kind]
    for key in (
        "country",
        "scheme",
        "subdivision",
        "limit",
        "prefer",
        "series",
        "scope",
    ):
        if request.get(key) is not None and kind != "ip":
            args.extend(["--" + key, str(request[key])])
    value = str(request["values"][0])
    return [*args, "--", value]


@pytest.mark.parametrize("name", BUNDLES)
def test_console_vectors(
    name: str, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    bundle = json.loads((FIXTURES / f"{name}-vectors.json").read_text())
    for pack in selection(FIXTURES / bundle["pack"]).values():
        install_fixture(tmp_path, pack)
    for case in bundle["cases"]:
        if case["id"] == "postal-025":
            # Numeric values cannot be preserved as typed values in OS argv.
            assert not isinstance(case["request"]["values"][0], str)
            with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
                assert resolve(geo, case["request"]).to_dict() == case["result"]
            with pytest.raises(TypeError):
                _core.run_cli(["thereabouts", "postal", case["request"]["values"][0]])
            continue
        args = arguments(case["request"])
        if any("\0" in arg for arg in args):
            # OS argv cannot contain NUL. Drive the same native runner through
            # its binding and assert the unchanged invalid-input expectation.
            code = _core.run_cli(["thereabouts", "--data-dir", str(tmp_path), *args])
            captured = capfd.readouterr()
            result = subprocess.CompletedProcess(args, code, captured.out, captured.err)
        else:
            result = console(tmp_path, *args)
        expected = case["result"]
        if case["id"] in USAGE_CASES:
            assert expected["status"] == "invalid_input"
            assert result.returncode == 2 and not result.stdout, case["id"]
            continue
        code = (
            2
            if expected["status"] in ("invalid_input", "unsupported_granularity")
            else 0
        )
        assert result.returncode == code, (case["id"], result.stderr)
        assert json.loads(result.stdout) == expected, case["id"]
