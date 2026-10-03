"""Bound reusable geometry without retaining an unbounded set of country payloads."""

from collections import OrderedDict
from collections.abc import Callable, Hashable
from threading import RLock
from typing import Generic, TypeVar

Key = TypeVar("Key", bound=Hashable)
Value = TypeVar("Value")


class Cache(Generic[Key, Value]):
    def __init__(self) -> None:
        self.values: OrderedDict[Key, Value] = OrderedDict()
        self.lock = RLock()

    def get(self, key: Key, make: Callable[[], Value], limit: int) -> Value:
        if limit <= 0:
            raise ValueError("Cache limit must be positive")
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
            else:
                while len(self.values) >= limit:
                    self.values.popitem(last=False)
                self.values[key] = make()
            while len(self.values) > limit:
                self.values.popitem(last=False)
            return self.values[key]
