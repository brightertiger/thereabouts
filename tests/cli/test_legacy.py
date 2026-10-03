"""Original postal/airport assertions also qualify the new real console."""

import json
from collections import Counter
from pathlib import Path

import pytest

from tests.conformance.forward_legacy import assert_case, assert_result
from tests.conformance.pack_selection import selection
from thereabouts import Geocoder, Result

from .helpers import FIXTURES, console, install_fixture
from .test_vectors import arguments


@pytest.mark.parametrize("family", ["postal", "airports"])
def test_legacy_expectations(family: str, tmp_path: Path) -> None:
    for pack in selection(FIXTURES / f"packs/{family}-synthetic").values():
        install_fixture(tmp_path, pack)
    counts: Counter[str] = Counter()
    kind = "airport" if family == "airports" else family
    for case in json.loads((FIXTURES / "conformance.json").read_text())["cases"]:
        if case["request"]["kind"] != kind:
            continue
        if case["id"] == 51:
            # The original integer-type rejection has no OS argv representation.
            with Geocoder(
                packs=selection(FIXTURES / f"packs/{family}-synthetic")
            ) as geo:
                counts[assert_case(geo, case)] += 1
            continue
        output = console(tmp_path, "--evidence", *arguments(case["request"]))
        if not output.stdout:
            assert "error" in case and output.returncode == 2
            assert case["error"]["name"] in {
                "ContextRequiredError",
                "InvalidInputError",
            }
            counts["invalid_input"] += 1
        else:
            assert output.returncode in (0, 2)
            answer = Result.from_dict(json.loads(output.stdout))
            counts[assert_result(answer, case)] += 1
    assert dict(counts) == (
        {"matched": 4, "ambiguous": 1, "not_found": 1, "invalid_input": 2}
        if family == "postal"
        else {"matched": 7, "ambiguous": 2, "not_found": 1, "invalid_input": 1}
    )
