"""Offline golden-pack API. Open a new handle in each process and reuse it."""

from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from .columns import Columns, columns
from .errors import ClosedGeocoderError
from .packs.address import address
from .reading.batch import lookup_rows
from .reading.decode import data_identity, resolution
from .reading.inputs import BATCH_SIZE, Errors, batch_options, coordinates, h3_cell
from .reading.pack import Pack
from .results import InputError, Query, Resolution


class Geocoder:
    """Read one immutable reverse pack; opening and lookups never use a network.

    ``verify=True`` checks every hash and structure before use. Normal opening
    checks inventory sizes, then validates container bounds on first shard use.
    It assumes an immutable, previously verified installation.
    """

    def __init__(self, pack: str | Path, *, verify: bool = False) -> None:
        self._lock = RLock()
        self._closed = False
        self._pack = Pack(Path(pack), verify=verify)
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
        shard = self._pack.spatial_for(block)
        found = None if shard is None else shard.lookup(block, key)
        return resolution(
            self._pack, self._data, query, cell, block, shard is not None, found
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
                if not chunk:
                    return
                answers = self._chunk(chunk, kind, errors)
            for answer in answers:
                with self._lock:
                    self._ensure_open()
                yield answer

    def _chunk(
        self,
        rows: list[object],
        kind: Literal["coordinates", "h3"],
        errors: Errors,
    ) -> list[Resolution]:
        answers = []
        for hit in lookup_rows(self._pack, rows, kind, errors):
            if hit.error is not None:
                answer = Resolution(
                    status="invalid_input",
                    selected=None,
                    candidates=(),
                    query=hit.query,
                    reference=None,
                    data=self._data,
                    error=InputError("invalid_input", hit.error),
                )
            else:
                answer = resolution(
                    self._pack,
                    self._data,
                    hit.query,
                    hit.cell,
                    hit.block,
                    hit.covered,
                    hit.found,
                )
            answers.append(answer)
        return answers

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
                if not chunk:
                    return
                hits = lookup_rows(self._pack, chunk, "coordinates", errors)
                result = columns(self._pack, self._data, hits, decode=decode)
            yield result

    def info(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            return {"backend": "python", "pack": self._pack.info()}

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
