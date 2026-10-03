"""Admission guard: pause on disk or memory pressure; never delete user data."""

import os
import resource
import shutil
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from pipeline.config.schema import Resources


def peak_rss() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def current_rss() -> int:
    return psutil.Process().memory_info().rss


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
            stat = path.stat()
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
        rss: Callable[[], int] = current_rss,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ) -> None:
        self.root, self.limits = root, limits
        self.free, self.used, self.rss = free, used, rss
        self.sleep, self.log = sleep, log
        self.lock = threading.Lock()
        self.reserved = 0

    def admit(self, required_bytes: int = 0) -> None:
        if required_bytes < 0:
            raise ValueError("A unit's disk reservation cannot be negative")
        while True:
            with self.lock:
                free, used, rss = self.free(self.root), self.used(self.root), self.rss()
                needed = self.reserved + required_bytes
                if (
                    free - needed >= self.limits.disk_floor
                    and used + needed <= self.limits.max_workspace
                    and rss <= self.limits.rss_limit
                ):
                    self.reserved += required_bytes
                    return
            self.log(
                f"paused: free={free}, workspace={used}, rss={rss}, "
                f"reserved={needed}; waiting for resource headroom"
            )
            self.sleep(self.limits.poll_seconds)

    def release(self, reserved_bytes: int) -> None:
        with self.lock:
            self.reserved -= reserved_bytes
