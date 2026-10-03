"""Low disk pauses and resumes without running or deleting a unit."""

from pathlib import Path

from pipeline.config.schema import Resources
from pipeline.runtime.resources import ResourceGuard


def test_disk_floor_pauses_then_admits_exact_boundary(tmp_path: Path) -> None:
    free = iter([4_999_999_999, 5_000_000_099, 5_000_000_100])
    pauses: list[float] = []
    messages: list[str] = []
    guard = ResourceGuard(
        tmp_path,
        Resources(),
        free=lambda _: next(free),
        used=lambda _: 0,
        rss=lambda: 0,
        sleep=pauses.append,
        log=messages.append,
    )
    guard.admit(100)
    assert len(pauses) == 2
    assert all("paused" in message for message in messages)
    assert guard.reserved == 100
    guard.release(100)
    assert guard.reserved == 0


def test_workers_share_reservations(tmp_path: Path) -> None:
    free = iter([5_000_000_150, 5_000_000_150, 5_000_000_200])
    pauses: list[float] = []
    guard = ResourceGuard(
        tmp_path,
        Resources(),
        free=lambda _: next(free),
        used=lambda _: 0,
        rss=lambda: 0,
        sleep=pauses.append,
        log=lambda _: None,
    )
    guard.admit(100)
    guard.admit(100)
    assert len(pauses) == 1
    assert guard.reserved == 200


def test_memory_pause_resumes_when_resident_usage_falls(tmp_path: Path) -> None:
    rss = iter([2_000_000_001, 2_000_000_000])
    pauses: list[float] = []
    guard = ResourceGuard(
        tmp_path,
        Resources(),
        free=lambda _: 10_000_000_000,
        used=lambda _: 0,
        rss=lambda: next(rss),
        sleep=pauses.append,
        log=lambda _: None,
    )
    guard.admit()
    assert len(pauses) == 1


def test_workspace_walk_is_cached_and_completed_bytes_are_accounted(
    tmp_path: Path,
) -> None:
    scans = []
    now = [0.0]

    def measured(root: Path) -> int:
        scans.append(root)
        return 100

    guard = ResourceGuard(
        tmp_path,
        Resources(),
        free=lambda _: 10_000_000_000,
        used=measured,
        rss=lambda: 0,
        clock=lambda: now[0],
    )
    for _ in range(1000):
        guard.admit(10)
        guard.release(10, written_bytes=7)
    assert scans == [tmp_path]
    assert guard.usage() == 7100
    now[0] = 60.0
    assert guard.usage() == 100
    assert scans == [tmp_path, tmp_path]
