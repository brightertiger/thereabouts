"""Offline golden-pack API. Open a new handle in each process and reuse it."""

from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from .client_errors import InvalidInputError
from .columns import Columns, columns
from .errors import ClosedGeocoderError
from .packs.address import address
from .reading.backend import Backend, select
from .reading.batch import lookup_rows
from .reading.decode import data_identity, resolution
from .reading.inputs import BATCH_SIZE, Errors, batch_options, coordinates, h3_cell
from .reading.objects import result
from .reading.pack import Pack
from .reading.places import DEFAULT_CACHE_BYTES
from .results import Query, Resolution
from .store import installed_pack


class Geocoder:
    """Read one immutable reverse pack; opening and lookups never use a network.

    ``verify=True`` checks every hash and structure before use. Normal opening
    checks inventory sizes, then validates container bounds on first shard use.
    It assumes an immutable, previously verified installation.
    """

    def __init__(
        self,
        pack: str | Path | None = None,
        *,
        data_dir: str | Path | None = None,
        verify: bool = False,
        backend: Backend = "auto",
        cache_bytes: int = DEFAULT_CACHE_BYTES,
    ) -> None:
        if pack is not None and data_dir is not None:
            raise InvalidInputError("Select a pack directory or a data store, not both")
        if type(cache_bytes) is not int or cache_bytes < 0:
            raise InvalidInputError("cache_bytes must be a nonnegative integer")
        selected = installed_pack(data_dir) if pack is None else Path(pack)
        self._backend, self._stored_cell = select(backend)
        self._lock = RLock()
        self._closed = False
        self._pack = Pack(selected, verify=verify, cache_bytes=cache_bytes)
        self._data = data_identity(self._pack)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedGeocoderError("Geocoder is closed")

    def reverse(self, latitude: float, longitude: float) -> Resolution:
        with self._lock:
            self._ensure_open()
            return self._one(*coordinates((latitude, longitude)))

    def from_h3(self, cell: str) -> Resolution:
        with self._lock:
            self._ensure_open()
            return self._one(*h3_cell(cell))

    def _one(self, cell: int, query: Query) -> Resolution:
        block, key = address(cell, 8)
        covered, found = self._pack.lookup(block, key)
        return resolution(
            self._pack,
            self._data,
            query,
            cell,
            block,
            covered,
            found,
            self._stored_cell,
        )

    def reverse_many(
        self,
        coordinates: Iterable[object],
        *,
        errors: Errors = "raise",
        chunk_size: int = BATCH_SIZE,
    ) -> Iterator[Resolution]:
        """Yield in input order; earlier chunks survive a later invalid row."""
        return self._many(coordinates, "coordinates", errors, chunk_size)

    def from_h3_many(
        self,
        cells: Iterable[object],
        *,
        errors: Errors = "raise",
        chunk_size: int = BATCH_SIZE,
    ) -> Iterator[Resolution]:
        return self._many(cells, "h3", errors, chunk_size)

    def _many(
        self,
        rows: Iterable[object],
        kind: Literal["coordinates", "h3"],
        errors: Errors,
        chunk_size: int,
    ) -> Iterator[Resolution]:
        with self._lock:
            self._ensure_open()
            batch_options(errors, chunk_size)
        return self._iterate(iter(rows), kind, errors, chunk_size)

    def _iterate(
        self,
        rows: Iterator[object],
        kind: Literal["coordinates", "h3"],
        errors: Errors,
        chunk_size: int,
    ) -> Iterator[Resolution]:
        while True:
            with self._lock:
                self._ensure_open()
                chunk = list(islice(rows, chunk_size))
                self._ensure_open()
                if not chunk:
                    return
                batch = lookup_rows(self._pack, chunk, kind, errors)
            for index in range(len(chunk)):
                with self._lock:
                    self._ensure_open()
                    answer = result(
                        self._pack, self._data, batch, index, self._stored_cell
                    )
                yield answer

    def reverse_columns(
        self,
        coordinates: Iterable[object],
        *,
        decode: bool = False,
        errors: Errors = "raise",
        chunk_size: int = BATCH_SIZE,
    ) -> Iterator[Columns]:
        """Yield numeric columns; decode=True adds the chunk's distinct places."""
        with self._lock:
            self._ensure_open()
            batch_options(errors, chunk_size)
        return self._column_iterator(iter(coordinates), decode, errors, chunk_size)

    def _column_iterator(
        self,
        rows: Iterator[object],
        decode: bool,
        errors: Errors,
        chunk_size: int,
    ) -> Iterator[Columns]:
        while True:
            with self._lock:
                self._ensure_open()
                chunk = list(islice(rows, chunk_size))
                self._ensure_open()
                if not chunk:
                    return
                hits = lookup_rows(self._pack, chunk, "coordinates", errors)
                result = columns(self._pack, self._data, hits, decode=decode)
            yield result

    def info(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            return {
                "backend": self._backend,
                "pack": self._pack.info(),
                "cache": self._pack.places.info(),
            }

    def explain(self, answer: Resolution) -> dict[str, Any]:
        """Return installed evidence and golden references, without fetching more."""
        with self._lock:
            self._ensure_open()
            return {"result": answer.to_dict(), "raw_evidence_installed": False}

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._pack.close()
                self._closed = True

    def __enter__(self) -> "Geocoder":
        with self._lock:
            self._ensure_open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
