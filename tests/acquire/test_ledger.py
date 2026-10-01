"""Checkpoint durability and concurrent independent source units."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from build_data.acquire import Ledger, atomic_output, fingerprint


def test_complete_reopen_and_input_changes(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    key = fingerprint({"input": "abc", "policy": 1})
    assert key == fingerprint({"policy": 1, "input": "abc"})
    assert not ledger.is_complete("geonames.normalize", "chunk-1", key)
    output = tmp_path / "output.json"
    with atomic_output(output, lambda p: json.loads(p.read_text())) as temporary:
        temporary.write_text('{"rows": 1}')
        assert not output.exists()
    ledger.complete(
        "geonames.normalize", "chunk-1", key, [output], metadata={"rows": 1}
    )
    reopened = Ledger(ledger.path)
    assert reopened.completed_outputs("geonames.normalize", "chunk-1", key) == (output,)
    assert not reopened.is_complete(
        "geonames.normalize", "chunk-1", fingerprint({"input": "abc", "policy": 2})
    )
    assert not reopened.is_complete("overture.normalize", "chunk-1", key)
    # Same size corruption must invalidate the unit, too.
    output.write_text('{"rows": 9}')
    assert not reopened.is_complete("geonames.normalize", "chunk-1", key)
    output.unlink()
    assert not reopened.is_complete("geonames.normalize", "chunk-1", key)


def test_failed_validation_preserves_old_output_and_no_completion(
    tmp_path: Path,
) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    output = tmp_path / "result.json"
    output.write_text('{"old": true}')
    with pytest.raises(json.JSONDecodeError):
        with atomic_output(output, lambda p: json.loads(p.read_text())) as temporary:
            temporary.write_text("unfinished")
        ledger.complete("stage", "unit", "hash", [output])
    assert output.read_text() == '{"old": true}'
    assert not ledger.is_complete("stage", "unit", "hash")
    assert not list(tmp_path.glob("*.part"))


def test_published_orphan_can_be_verified_and_adopted(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    output = tmp_path / "result.json"
    with atomic_output(output, lambda p: json.loads(p.read_text())) as temporary:
        temporary.write_text('{"rows": 1}')
    # A crash here leaves valid output but no record, so a restart cannot skip it.
    assert not ledger.is_complete("stage", "unit", "hash")
    assert json.loads(output.read_text()) == {"rows": 1}
    ledger.complete("stage", "unit", "hash", [output])
    assert ledger.is_complete("stage", "unit", "hash")


def test_rejects_unpublished_and_missing_outputs(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    temporary = tmp_path / "result.part"
    temporary.write_bytes(b"bytes")
    for path in (temporary, tmp_path / "missing"):
        with pytest.raises(ValueError, match="not been published"):
            ledger.complete("stage", "unit", "hash", [path])
    assert not ledger.is_complete("stage", "unit", "hash")


def test_empty_unit_and_four_concurrent_sources(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"

    def run(index: int) -> None:
        ledger = Ledger(ledger_path)
        path = tmp_path / str(index)
        path.write_text(str(index))
        ledger.complete(f"source{index}.normalize", "unit", "hash", [path])

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(run, range(4)))
    ledger = Ledger(ledger_path)
    for index in range(4):
        assert ledger.is_complete(f"source{index}.normalize", "unit", "hash")
    ledger.complete("empty", "unit", "hash", [], metadata={"rows": 0})
    assert ledger.completed_outputs("empty", "unit", "hash") == ()


def test_interruption_during_output_write_never_completes(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    output = tmp_path / "result"
    with (
        pytest.raises(InterruptedError),
        atomic_output(output, lambda p: None) as temporary,
    ):
        temporary.write_bytes(b"incomplete")
        raise InterruptedError("interrupted")
    assert not output.exists()
    assert not ledger.is_complete("stage", "unit", "hash")


def _open_in_process(path: str, number: int, barrier: object) -> None:
    from typing import Any, cast

    cast(Any, barrier).wait(timeout=20)
    ledger = Ledger(Path(path))
    digest = fingerprint({"process": number})
    ledger.complete("parallel.normalize", str(number), digest, [])
    assert ledger.is_complete("parallel.normalize", str(number), digest)


def test_simultaneous_first_open_from_processes(tmp_path: Path) -> None:
    import multiprocessing

    # spawn exercises independent SQLite handles and module initialization.
    context = multiprocessing.get_context("spawn")
    for trial in range(3):
        path = tmp_path / f"trial-{trial}.sqlite3"
        barrier = context.Barrier(6)
        processes = [
            context.Process(target=_open_in_process, args=(str(path), n, barrier))
            for n in range(6)
        ]
        for process in processes:
            process.start()
        try:
            for process in processes:
                process.join(timeout=30)
                assert process.exitcode == 0
            ledger = Ledger(path)
            for n in range(6):
                assert ledger.is_complete(
                    "parallel.normalize", str(n), fingerprint({"process": n})
                )
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()
