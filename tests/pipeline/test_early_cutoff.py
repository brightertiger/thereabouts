"""Identity-only upstream changes stop at consumers when the bytes are identical."""

from pathlib import Path

from pipeline.config import load
from pipeline.runtime.jsonio import encode
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.outputs import receipt_digest, role
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import make_unit

from .helpers import HashedStage, SyntheticStage, context

HASH = "a" * 64


def writable(root: Path) -> Ledger:
    return Ledger(
        root,
        root / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    )


def consumer(*dependencies: Dependency) -> SyntheticStage:
    return SyntheticStage(
        "second", [Recipe("second", "one", dependencies=dependencies)], needs=("first",)
    )


def test_identity_only_change_under_inputs_hash_skips_consumer(tmp_path: Path) -> None:
    first = HashedStage("first", [Recipe("first", "one")])
    second = consumer(Dependency("first", "one"))
    with writable(tmp_path) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, [first, second])
        before = ledger.get("first", "one")
        first.implementation = "changed code, same bytes"
        assert run(ctx, [first, second]) == {"completed": 1, "skipped": 1}
        after = ledger.get("first", "one")
        assert before and after and before.outputs[0].path != after.outputs[0].path
        assert second.calls == ["one"]
        first.content = "changed bytes"
        first.implementation = "changed again"
        assert run(ctx, [first, second]) == {"completed": 2, "skipped": 0}
        assert second.calls == ["one", "one"]


def test_dependency_paths_are_role_patterns(tmp_path: Path) -> None:
    first = HashedStage("first", [Recipe("first", "one")])
    data = consumer(Dependency("first", "one", paths=("first/one",)))
    with writable(tmp_path) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, [first, data])
        first.note, first.implementation = "receipt changed", "changed"
        assert run(ctx, [first, data]) == {"completed": 1, "skipped": 1}
        whole = consumer(Dependency("first", "one"))
        run(ctx, [first, whole])
        first.note, first.implementation = "receipt changed again", "again"
        assert run(ctx, [first, whole])["completed"] == 2


def test_roles_drop_inputs_hash_directories_only() -> None:
    assert role(f"cells/base/{HASH}/cells/x.parquet") == "cells/base/cells/x.parquet"
    assert role(f"raw/src/sha256/{HASH}") == f"raw/src/sha256/{HASH}"
    assert role(f"normalized/a/places/{HASH}/{HASH}-00000.parquet") == (
        f"normalized/a/places/{HASH}-00000.parquet"
    )
    assert role("https://example.org/a/b") == "https://example.org/a/b"


def test_receipt_digest_ignores_inputs_hash_locations_only() -> None:
    def receipt(directory: str, sha: str) -> bytes:
        record = {"path": f"x/{directory}/f.parquet", "sha256": sha, "size": 3}
        return encode({"t": record, "label": "kept"})

    first, second = receipt("a" * 64, "1" * 64), receipt("b" * 64, "1" * 64)
    assert receipt_digest(first) == receipt_digest(second) is not None
    assert receipt_digest(second) != receipt_digest(receipt("b" * 64, "2" * 64))
    assert receipt_digest(encode({"path": "x/f.parquet"})) is None
    assert receipt_digest(b"not json") is None


def test_units_never_share_an_inputs_hash(tmp_path: Path) -> None:
    with writable(tmp_path) as ledger:
        ctx = context(tmp_path, ledger)
        one, two = (make_unit(ctx, Recipe("first", key), "same") for key in "ab")
        assert one.inputs_hash != two.inputs_hash
