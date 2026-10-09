"""Transient transfer failures are retried with jittered backoff inside a budget."""

import io
from collections.abc import Callable
from email.message import Message
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError

import pytest

from pipeline.config import load
from pipeline.config.sources import SourceLimits, validate_source
from pipeline.storage.retry import Interrupted, Patience, retrying, transient


def status(code: int) -> HTTPError:
    return HTTPError("http://127.0.0.1/x", code, "status", Message(), io.BytesIO())


class RemoteError(Exception):
    """Object-store drivers report HTTP statuses on a `code` attribute."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


def patience(
    clock: Clock,
    *,
    retries: int = 5,
    backoff: float = 1.0,
    cap: float = 60.0,
    budget: float = 900.0,
) -> Patience:
    return Patience(retries, backoff, cap, budget, clock=clock, sleep=clock.sleep)


def failing(errors: list[BaseException]) -> tuple[Callable[[], str], list[int]]:
    calls: list[int] = []

    def attempt() -> str:
        calls.append(len(calls))
        if errors:
            raise errors.pop(0)
        return "done"

    return attempt, calls


@pytest.mark.parametrize(
    "error",
    [
        status(403),
        status(404),
        status(412),
        status(416),
        RemoteError(404),
        FileNotFoundError("gone"),
        PermissionError("denied"),
        ValueError("Object does not match its pinned size and SHA256"),
    ],
)
def test_deterministic_failures_are_not_retried(error: Exception) -> None:
    clock = Clock()
    attempt, calls = failing([error])
    assert not transient(error)
    with pytest.raises(type(error)):
        retrying(patience(clock), attempt)
    assert len(calls) == 1 and clock.pauses == []


@pytest.mark.parametrize(
    "error",
    [
        status(408),
        status(429),
        status(500),
        status(503),
        RemoteError(503),
        URLError("connection refused"),
        ConnectionResetError("reset"),
        TimeoutError("timed out"),
        IncompleteRead(b"partial", 10),
        Interrupted("short body"),
    ],
)
def test_transient_failures_are_retried(error: Exception) -> None:
    clock = Clock()
    attempt, calls = failing([error, error])
    assert retrying(patience(clock), attempt) == "done"
    assert len(calls) == 3 and len(clock.pauses) == 2


def test_backoff_doubles_with_jitter_up_to_its_cap() -> None:
    clock = Clock()
    attempt, _ = failing([Interrupted("short body") for _ in range(7)])
    retrying(patience(clock, retries=7, cap=4.0), attempt)
    bounds = [1.0, 2.0, 4.0, 4.0, 4.0, 4.0, 4.0]
    assert len(clock.pauses) == len(bounds)
    assert all(
        bound / 2 <= pause <= bound
        for pause, bound in zip(clock.pauses, bounds, strict=True)
    )


def test_consecutive_failures_are_bounded_by_retries() -> None:
    clock = Clock()
    attempt, calls = failing([Interrupted("short body") for _ in range(4)])
    with pytest.raises(Interrupted):
        retrying(patience(clock, retries=3), attempt)
    assert len(calls) == 4


def test_patience_budget_stops_before_the_retry_count() -> None:
    clock = Clock()
    attempt, calls = failing([Interrupted("short body") for _ in range(50)])
    with pytest.raises(Interrupted):
        retrying(patience(clock, retries=50, cap=4.0, budget=10.0), attempt)
    assert clock.now <= 10.0 and len(calls) < 10


def test_progress_resets_the_retry_count_and_the_budget() -> None:
    clock = Clock()
    received = [0]

    def attempt() -> str:
        received[0] += 1
        clock.now += 100.0  # every attempt is slow but keeps more bytes
        if received[0] < 10:
            raise Interrupted("connection dropped")
        return "done"

    result = retrying(
        patience(clock, retries=2, budget=150.0), attempt, lambda: received[0]
    )
    assert result == "done" and received[0] == 10


def test_default_limits_give_fifteen_minutes_of_patience() -> None:
    limits = SourceLimits()
    result = Patience.of(limits)
    assert (result.retries, result.backoff, result.cap, result.budget) == (
        20,
        1.0,
        60.0,
        900.0,
    )


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf")])
def test_source_patience_must_be_positive_and_finite(value: float) -> None:
    source = load().sources["airports"]
    source.limits.patience_seconds = value
    with pytest.raises(ValueError, match="retry limits"):
        validate_source(source)
