"""Pipeline paths and local disk budgets (decimal GB)."""

import hashlib
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .lookup_catalog import LOOKUP_SOURCES

SOURCES = ("ghsl", "osm_land", "overture", "geonames", "geoboundaries", *LOOKUP_SOURCES)
MIN_FREE_BYTES = 12_000_000_000
MAX_WORKSPACE_BYTES = 60_000_000_000


@dataclass(frozen=True)
class Workspace:
    """Paths rooted at data/, with one shared ledger and source-owned directories."""

    root: Path = Path("data")

    def raw(self, source: str) -> Path:
        """Return the immutable raw download directory for a supported source."""
        self._check_source(source)
        return self.root / "raw" / source

    def normalized(self, source: str) -> Path:
        """Return the normalized Parquet root for a supported source."""
        self._check_source(source)
        return self.root / "normalized" / source

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def ledger_path(self) -> Path:
        return self.work / "ledger.sqlite3"

    def partition(
        self, source: str, kind: str, unit_id: str, inputs_hash: str, part: int = 0
    ) -> Path:
        """Return a deterministic path; input changes cannot overwrite prior outputs."""
        from .lookup_schemas import KINDS

        if kind not in ("areas", "places", "names", *KINDS) or part < 0:
            raise ValueError("Invalid partition kind or part number")
        if len(inputs_hash) != 64 or any(
            c not in "0123456789abcdef" for c in inputs_hash
        ):
            raise ValueError("inputs_hash must be a lowercase SHA256")
        unit = hashlib.sha256(unit_id.encode("utf-8")).hexdigest()
        return (
            self.normalized(source) / kind / inputs_hash / f"{unit}-{part:05d}.parquet"
        )

    def prepare(self) -> None:
        """Create source directories and the temporary root without acquiring data."""
        self.work.mkdir(parents=True, exist_ok=True)
        for source in SOURCES:
            self.raw(source).mkdir(parents=True, exist_ok=True)
            self.normalized(source).mkdir(parents=True, exist_ok=True)

    def check_budget(self, required_bytes: int = 0) -> None:
        """Refuse new work below 12 GB free or above the 60 GB workspace cap."""
        if required_bytes < 0:
            raise ValueError("required_bytes must be nonnegative")
        self.root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.root).free
        if free - required_bytes < MIN_FREE_BYTES:
            raise OSError(
                "Disk budget: preserve at least 12 GB free before starting a unit"
            )
        used = 0
        for path in self.root.rglob("*"):
            try:
                entry = path.lstat()
            except FileNotFoundError:
                # Another source may have just published or cleaned a temporary.
                continue
            if stat.S_ISREG(entry.st_mode):
                used += entry.st_size
        if used + required_bytes > MAX_WORKSPACE_BYTES:
            raise OSError("Disk budget: workspace would exceed 60 GB")

    @staticmethod
    def _check_source(source: str) -> None:
        if source not in SOURCES:
            raise ValueError(f"Unknown source: {source}")
