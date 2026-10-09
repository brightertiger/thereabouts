"""A world-shaped core opens, queries and verifies at ulimit -n 256 in every client.

The macOS default soft limit is 256 descriptors. A world core has 14,847 stored
r3 blocks; before shard grouping and the bounded handle pool it held about 15.4 k
files open and failed with EMFILE in Python, the CLI and the writer itself.
"""

import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

import h3
import pytest

from tests.client.hosts import console, node_console, python
from tests.tools import world_shape

LIMIT = 256
# Packs are written in child processes under the limit: the writer's own full
# verification must stream shard by shard too.
WRITE = """
import json, sys
from thereabouts import _core
_core.write_pack(sys.argv[1], "core", sys.argv[2], json.loads(sys.argv[3]))
"""


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("world")
    golden = world_shape.dataset(root / "dataset", places=12_000, evidence_bytes=3200)
    targets = {"world": {}, "sharded": {"shard_bytes": 128 * 1024}}
    writers = {
        name: subprocess.Popen(
            [
                "/bin/sh",
                "-c",
                f'ulimit -n {LIMIT} && exec "$0" -c "$1" "$2" "$3" "$4"',
                sys.executable,
                WRITE,
                str(golden),
                str(root / name),
                json.dumps(world_shape.options(**extra)),
            ],
            stderr=subprocess.PIPE,
            text=True,
        )
        for name, extra in targets.items()
    }
    for name, writer in writers.items():
        _, stderr = writer.communicate(timeout=600)
        assert writer.returncode == 0, (name, stderr)
    return {name: root / name for name in targets} | {
        f"{name}-release": world_shape.release(root / name, root / f"{name}-release")
        for name in targets
    }


def kinds(pack: Path) -> Counter[str]:
    manifest = json.loads((pack / "manifest.json").read_text())
    return Counter(f["kind"] for f in manifest["files"])


def cells(count: int) -> list[str]:
    """Stored block centres plus arbitrary cells, most of them outside coverage."""
    rng = random.Random(20261009)
    stored = rng.sample(world_shape.blocks(), count)
    anywhere = [
        h3.latlng_to_cell(rng.uniform(-85, 85), rng.uniform(-180, 180), 8)
        for _ in range(count // 4)
    ]
    return [h3.cell_to_center_child(b, 8) for b in stored] + anywhere


def test_world_core_is_complete_in_few_files(world: dict[str, Path]) -> None:
    files = sum(kinds(world["world"]).values()) + 1
    assert files < 200, files
    assert kinds(world["world"])["catalogue"] >= 2
    # The sharded copy exceeds both the limit and the default 64-handle pool.
    assert sum(kinds(world["sharded"]).values()) > LIMIT


QUERY = """
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
from thereabouts import Geocoder
world, sharded, cells = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
fd = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
with Geocoder(world, verify=True) as one, Geocoder(sharded, verify=True) as many:
    expected = {c: one.from_h3(c, evidence=True).to_dict() for c in cells}
    def check(part):
        return [many.from_h3(c, evidence=True).to_dict() == expected[c] for c in part]
    with ThreadPoolExecutor(8) as pool:
        parts = pool.map(check, [cells[i::8] for i in range(8)])
        same = [ok for part in parts for ok in part]
    value = {"same": all(same), "count": len(same), "fds": len(os.listdir(fd))}
    value["statuses"] = sorted({v["status"] for v in expected.values()})
print(json.dumps(value))
"""


def test_eight_threads_over_more_shards_than_handles(world: dict[str, Path]) -> None:
    sample = cells(2000)
    result = python(
        QUERY,
        str(world["world"]),
        str(world["sharded"]),
        json.dumps(sample),
        open_files=LIMIT,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["same"] and value["count"] == len(sample)
    assert value["statuses"] == ["matched", "not_found"]
    # Two packs: at most 64 idle handles each, plus interpreter descriptors.
    assert value["fds"] < 160, value


@pytest.mark.parametrize("name", ["world", "sharded"])
@pytest.mark.parametrize("host", ["cli", "node"])
def test_install_query_and_full_verify_at_the_limit(
    world: dict[str, Path], tmp_path: Path, name: str, host: str
) -> None:
    run = console if host == "cli" else node_console
    store = str(tmp_path / "store")
    release = str(world[f"{name}-release"])
    lat, lon = h3.cell_to_latlng(h3.cell_to_center_child(world_shape.blocks()[7000], 8))
    for args in (
        ["data", "install", "core", "--from", release],
        ["data", "verify", "--full"],
        ["reverse", "--lat", str(lat), "--lon", str(lon), "--json"],
    ):
        result = run("--data-dir", store, *args, open_files=LIMIT)
        assert result.returncode == 0, (args, result.stderr)
    answer = json.loads(result.stdout)
    assert answer["status"] == "matched"
    assert answer["city"]["id"].startswith("city:world:")
