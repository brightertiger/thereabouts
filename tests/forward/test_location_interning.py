"""Writer regression: a real origin point is distinct from a null location row."""

import hashlib
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from thereabouts import Geocoder, _core


def test_unassigned_origin_survives_location_interning(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures/datasets/forward-synthetic"
    dataset = tmp_path / "dataset"
    shutil.copytree(source, dataset)
    path = dataset / "golden/manifest.json"
    manifest = json.loads(path.read_text())
    table = next(t for t in manifest["tables"] if t["kind"] == "postal_codes")
    parquet = path.parent / manifest["data_root"] / table["path"]
    original = pq.read_table(parquet)
    rows = original.to_pylist()
    row = next(r for r in rows if r["source_id"] == "p6")
    row.update(latitude=0.0, longitude=0.0, place_name=None)
    pq.write_table(pa.Table.from_pylist(rows, schema=original.schema), parquet)
    table.update(
        sha256=hashlib.sha256(parquet.read_bytes()).hexdigest(),
        size=parquet.stat().st_size,
    )
    path.write_text(json.dumps(manifest))
    pack = tmp_path / "postal"
    _core.write_pack(str(path.parent), "postal", str(pack), {"data_version": "test"})
    with Geocoder(pack, verify=True) as geo:
        answer = geo.postal("VOID", country="AA", evidence=True)
        assert answer.status == "matched"
        assert answer.point is not None
        assert (answer.point.lat, answer.point.lon) == (0.0, 0.0)
