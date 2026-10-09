"""Retry transient transfer failures with jittered backoff and a patience budget."""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from typing import TypeVar

from pipeline.config.sources import SourceLimits

T = TypeVar("T")

# Waiting cannot create a missing object or grant a refused permission.
PERMANENT = (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError)


class Interrupted(ConnectionError):
    """A transfer ended early; the next attempt resumes or restarts it."""


def transient(error: BaseException) -> bool:
    # urllib's HTTPError and object-store drivers both report statuses as `code`.
    code = getattr(error, "code", None)
    if isinstance(code, int) and 400 <= code < 600:
        return code in (408, 429) or code >= 500
    if isinstance(error, PERMANENT):
        return False
    return isinstance(error, (OSError, HTTPException))


@dataclass(frozen=True)
class Patience:
    retries: int
    backoff: float
    cap: float
    budget: float
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def of(cls, limits: SourceLimits) -> "Patience":
        return cls(
            limits.retries,
            limits.backoff_seconds,
            limits.timeout_seconds,
            limits.patience_seconds,
        )


def retrying(
    patience: Patience, attempt: Callable[[], T], progress: Callable[[], int] = int
) -> T:
    """Give up after `retries` failures or `budget` seconds without new progress."""
    best, failures = progress(), 0
    delay, since = patience.backoff, patience.clock()
    while True:
        try:
            return attempt()
        except Exception as error:
            if not transient(error):
                raise
            reached = progress()
            if reached > best:
                best, failures = reached, 0
                delay, since = patience.backoff, patience.clock()
            failures += 1
            pause = random.uniform(delay / 2, delay)
            if (
                failures > patience.retries
                or patience.clock() - since + pause > patience.budget
            ):
                raise
            patience.sleep(pause)
            delay = min(patience.cap, delay * 2)
