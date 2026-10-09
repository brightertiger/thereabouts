"""Bound reusable geometry without retaining an unbounded set of country payloads."""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from contextlib import AbstractContextManager, nullcontext
from threading import RLock
from typing import Generic, TypeVar

Key = TypeVar("Key", bound=Hashable)
Value = TypeVar("Value")


class Cache(Generic[Key, Value]):
    """A bounded LRU; `per_thread` keeps one per worker thread for values, such as
    prepared GEOS geometries, that must not be used from two threads at once."""

    def __init__(self, *, per_thread: bool = False) -> None:
        self.local = threading.local() if per_thread else None
        self.shared: OrderedDict[Key, Value] = OrderedDict()
        self.lock: AbstractContextManager[object] = (
            nullcontext() if per_thread else RLock()
        )

    @property
    def values(self) -> OrderedDict[Key, Value]:
        if self.local is None:
            return self.shared
        if not hasattr(self.local, "values"):
            self.local.values = OrderedDict()
        values: OrderedDict[Key, Value] = self.local.values
        return values

    def get(self, key: Key, make: Callable[[], Value], limit: int) -> Value:
        if limit <= 0:
            raise ValueError("Cache limit must be positive")
        with self.lock:
            values = self.values
            if key in values:
                values.move_to_end(key)
            else:
                while len(values) >= limit:
                    values.popitem(last=False)
                values[key] = make()
            while len(values) > limit:
                values.popitem(last=False)
            return values[key]
