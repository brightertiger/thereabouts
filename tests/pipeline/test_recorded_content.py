"""Recorded outputs hold neither their own location, identity nor wall-clock time."""

import json
from pathlib import Path
from typing import Any

from pipeline.runtime.jsonio import JSON
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.runner import run

from .geographic_fixtures import build, geographic_graph, source_receipts
from .sources.fixtures import archive, source_context
from .sources.test_shapes import shapes

FORBIDDEN = {"inputs_hash", "builder", "implementation", "units", "digest"}


def strings_and_keys(value: JSON) -> tuple[set[str], set[str]]:
    strings: set[str] = set()
    keys: set[str] = set()
    if isinstance(value, str):
        strings.add(value)
    elif isinstance(value, list):
        for item in value:
            inner = strings_and_keys(item)
            strings |= inner[0]
            keys |= inner[1]
    elif isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            inner = strings_and_keys(item)
            strings |= inner[0]
            keys |= inner[1]
    return strings, keys


def test_geographic_outputs_omit_identity_hashes_and_timings(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path, ledger)
        stages = geographic_graph(ctx, normalized)
        build(ctx, stages)
        records = list(ledger.records())
        assert {record.stage for record in records} >= {"lookups", "normalize_cells"}
        hashes = {record.inputs_hash for record in records} | {
            str(record.metadata["identity"]) for record in records
        }
        checked = 0
        for record in records:
            for output in record.outputs:
                if not output.path.endswith(".json"):
                    continue
                strings, keys = strings_and_keys(
                    json.loads((tmp_path / output.path).read_bytes())
                )
                assert not keys & FORBIDDEN, output.path
                assert not [key for key in keys if key.endswith("seconds")]
                assert not strings & hashes, output.path
                checked += 1
        assert checked > 10
        block = "block/" + ctx.config.engines.blocks[0]
        before = ledger.get("cells", block)
        ledger.invalidate("cells", [block])
        assert build(ctx, stages)["completed"] == 1
        after = ledger.get("cells", block)
        assert before and after and after.outputs == before.outputs


def boundary_payloads(root: Path) -> dict[str, tuple[bytes, dict[str, Any]]]:
    members = shapes(
        root,
        ["shapeName", "shapeISO", "shapeID", "shapeType"],
        [["Town", "GB-ENG", "boundary-id", "ADM1"]],
    )
    metadata = {
        "boundaryISO": "GBR",
        "boundaryType": "ADM1",
        "boundaryID": "GBR-ADM1-test",
        "boundaryLicense": "CC BY-SA 2.0",
        "boundarySource": "Synthetic contributor",
        "licenseSource": "example.test/licence",
        "admUnitCount": "1",
    }
    return {
        "boundaries.zip": (archive(members), {"metadata": metadata, "commit": "a" * 40})
    }


def test_forced_boundary_normalization_is_byte_identical(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path, ledger, "geoboundaries", boundary_payloads(tmp_path)
        )
        source.pin.metadata["country_reference"] = {"GBR": {"alpha2": "GB"}}
        run(source.runtime, stages)
        before = ledger.get("normalize", "geoboundaries")
        assert before is not None
        assert any("/audits/" in output.path for output in before.outputs)
        ledger.invalidate("normalize", ["geoboundaries"])
        assert run(source.runtime, stages) == {"completed": 1, "skipped": 1}
        after = ledger.get("normalize", "geoboundaries")
        assert after is not None and after.outputs == before.outputs
        manifest = json.loads((source.normalized / "manifest.json").read_bytes())
        assert "units" not in manifest
        assert "retries" not in manifest["configuration"]["limits"]
        assert "upstream" not in manifest["configuration"]
