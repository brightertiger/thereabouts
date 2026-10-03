"""Re-derive retained base and city products into the opt-in proof directory."""

from pathlib import Path

from pipeline.config import Config
from pipeline.engines.cells import build as cells
from pipeline.engines.cells.inputs import Inputs
from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.cities import build as cities
from pipeline.engines.cities import mapping
from pipeline.engines.cities.engine import Engine
from pipeline.engines.cities.schemas import MAPPING
from pipeline.engines.cities.urban import Urban
from pipeline.engines.reconcile.common import Row
from pipeline.engines.storage import parquet
from pipeline.runtime.jsonio import sha256_file


def base_cells(
    output: Path,
    block: str,
    source: Path,
    physical: Path,
    policy: Row,
    expected: Row,
    config: Config,
) -> Row:
    inputs = Inputs(
        {"MY": {"path": str(source)}},
        {"path": str(physical)},
        policy,
        {"MY"},
        config.engines.limits,
    )
    rows, counts = cells.build(int(block, 16), inputs, ["MY"], exhaustive=True)
    path = output / "base.parquet"
    made = parquet(output, path, rows, CELLS, config.engines.limits.parquet_batch_rows)
    assert made["sha256"] == expected["sha256"]
    assert made["rows"] == expected["rows"]
    return {**made, "kind": "base_cells", "counts": counts}


def city_products(
    output: Path, source: Path, urban: Urban, policy: Row, expected: Row, config: Config
) -> tuple[Path, list[Row]]:
    root = output / "cities/MY"
    result = cities.build_country(
        output,
        root,
        "MY",
        source,
        urban,
        policy,
        expected["digest"],
        config.engines.limits,
    )
    index = root / "index.sqlite"
    assert sha256_file(index) == expected["index"]["sha256"]
    assert result["table"]["sha256"] == expected["table"]["sha256"]
    selector = Engine(index, source, urban, policy, limits=config.engines.limits)
    made = parquet(
        output,
        root / "place_to_city.parquet",
        mapping.rows(selector, config.engines.limits.mapping_batch_rows),
        MAPPING,
        config.engines.limits.parquet_batch_rows,
    )
    assert made["sha256"] == expected["mapping"]["sha256"]
    assert made["rows"] == expected["mapping"]["rows"]
    return index, [
        {"kind": "city_index", **result["index"]},
        {"kind": "canonical_cities", **result["table"]},
        {"kind": "place_to_city", **made},
    ]
