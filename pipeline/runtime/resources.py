"""Admission guard: pause on disk or memory pressure, fail after a bounded wait."""

import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from pipeline.config.schema import Resources


def process_memory(pid: int) -> int:
    """PSS where the kernel reports it, so pages a forked worker still shares
    with its parent count once across the tree; resident size elsewhere."""
    try:
        with open(f"/proc/{pid}/smaps_rollup", "rb") as stream:
            for line in stream:
                if line.startswith(b"Pss:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        return int(psutil.Process(pid).memory_info().rss)
    except psutil.Error:
        return 0


def tree_memory() -> int:
    """This process and every descendant, such as unit worker processes."""
    process = psutil.Process()
    pids = [process.pid, *(child.pid for child in process.children(recursive=True))]
    return sum(process_memory(pid) for pid in pids)


class Sampled:
    """Reuse one measurement for an interval: PSS walks every page table."""

    def __init__(
        self, measure: Callable[[], int], seconds: float, clock: Callable[[], float]
    ) -> None:
        self.measure, self.seconds, self.clock = measure, seconds, clock
        self.value: int | None = None
        self.at = 0.0

    def __call__(self) -> int:
        if self.value is None or self.clock() - self.at >= self.seconds:
            self.value, self.at = self.measure(), self.clock()
        return self.value


def disk_free(root: Path) -> int:
    while not root.exists():
        root = root.parent
    return shutil.disk_usage(root).free


def workspace_bytes(root: Path) -> int:
    total = 0
    inodes: set[tuple[int, int]] = set()
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                # Installers and workers can retire staging files during the walk.
                continue
            key = stat.st_dev, stat.st_ino
            if key not in inodes:
                inodes.add(key)
                total += stat.st_size
    return total


class ResourceGuard:
    def __init__(
        self,
        root: Path,
        limits: Resources,
        *,
        free: Callable[[Path], int] = disk_free,
        used: Callable[[Path], int] = workspace_bytes,
        rss: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root, self.limits = root, limits
        self.free, self.used = free, used
        # Memory is summed over the process tree in the process that owns the
        # guard; worker processes ask it for admission.
        self.rss = rss or Sampled(tree_memory, limits.memory_scan_seconds, clock)
        self.sleep, self.log = sleep, log
        self.clock = clock
        self.lock = threading.Lock()
        self.scan_lock = threading.Lock()
        self.reserved = 0
        self.measured: int | None = None
        self.measured_at = 0.0
        self.growth = 0

    def usage(self) -> int:
        with self.lock:
            if (
                self.measured is not None
                and self.clock() - self.measured_at < self.limits.workspace_scan_seconds
            ):
                return self.measured
        with self.scan_lock:
            with self.lock:
                if (
                    self.measured is not None
                    and self.clock() - self.measured_at
                    < self.limits.workspace_scan_seconds
                ):
                    return self.measured
                previous_growth = self.growth
            # Do not hold the admission/reservation lock during the filesystem walk.
            measured = self.used(self.root)
            with self.lock:
                self.measured = measured + self.growth - previous_growth
                self.measured_at = self.clock()
                return self.measured

    def refresh_usage(self) -> None:
        """Reconcile streamed allocations and scratch removal at a unit boundary."""
        with self.lock:
            self.measured = None
        self.usage()

    def attempt(self, required_bytes: int) -> str | None:
        """Reserve and return None, or return the limits that leave no headroom."""
        if required_bytes < 0:
            raise ValueError("A unit's disk reservation cannot be negative")
        limits = self.limits
        self.usage()
        with self.lock:
            free, used, rss = self.free(self.root), self.measured or 0, self.rss()
            needed = self.reserved + required_bytes
            exhausted = [
                name
                for name, fits in (
                    ("disk_floor", free - needed >= limits.disk_floor),
                    ("max_workspace", used + needed <= limits.max_workspace),
                    ("rss_limit", rss <= limits.rss_limit * limits.workers),
                )
                if not fits
            ]
            if not exhausted:
                self.reserved += required_bytes
                return None
        return (
            f"{', '.join('resources.' + name for name in exhausted)} "
            f"(free={free}, workspace={used}, rss={rss}, reserved={needed})"
        )

    def refusal(self, waited: float, reason: str) -> str:
        return (
            f"Admission waited {waited:.0f}s on {reason}; remove superseded "
            "outputs with `python -m pipeline gc` or raise the limit"
        )

    def admit(self, required_bytes: int = 0) -> None:
        started = self.clock()
        while (reason := self.attempt(required_bytes)) is not None:
            waited = self.clock() - started
            if waited >= self.limits.admission_timeout_seconds:
                raise ValueError(self.refusal(waited, reason))
            self.log(f"paused on {reason}; waiting for resource headroom")
            self.sleep(self.limits.poll_seconds)

    def release(self, reserved_bytes: int, *, written_bytes: int | None = None) -> None:
        with self.lock:
            self.reserved -= reserved_bytes
            written = reserved_bytes if written_bytes is None else written_bytes
            self.growth += written
            if self.measured is not None:
                self.measured += written
