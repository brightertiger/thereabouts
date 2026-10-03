import json
from typing import Any, Literal

import pytest

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.commandline.application import main

from .generate import FIXTURES, OUTPUT, bundle, resolve

CASES = json.loads(OUTPUT.read_text())["cases"]


def test_vectors_are_current() -> None:
    assert json.loads(OUTPUT.read_text()) == bundle()


@pytest.mark.parametrize("backend", ["python", "auto"])
@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_reference(case: dict[str, Any], backend: Literal["python", "auto"]) -> None:
    with Geocoder(FIXTURES / case["pack"], backend=backend) as geo:
        if "error" in case:
            with pytest.raises(InvalidInputError) as caught:
                resolve(geo, case["request"])
            assert type(caught.value).__name__ == case["error"]["name"]
            assert str(caught.value) == case["error"]["message"]
        else:
            assert resolve(geo, case["request"]).to_dict() == case["result"]


@pytest.mark.parametrize(
    "case", [c for c in CASES if "result" in c], ids=lambda c: str(c["id"])
)
def test_cli(case: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    request = case["request"]
    kind = request["kind"]
    args = [
        "--pack",
        str(FIXTURES / case["pack"]),
        "reverse" if kind == "coordinates" else kind,
    ]
    args += [str(value) for value in request["values"]]
    for key in ("country", "scheme"):
        if request.get(key) is not None:
            args += ["--" + key, request[key]]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == case["result"]
