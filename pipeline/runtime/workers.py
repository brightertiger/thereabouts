"""Run units on threads of this process, or in forked worker processes.

Process workers keep every ledger write, admission decision and log line in
the parent, which owns the only ledger connection and the resource guard. A
child only runs units: it reads ledger records and asks for admission over its
pipe, and returns described outputs. Children ignore SIGINT, so a first Ctrl-C
lets running units finish, and they exit with the parent.
"""

import contextlib
import ctypes
import multiprocessing
import pickle
import signal
import sys
import threading
import time
import traceback
import warnings
from collections.abc import Callable, Container, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from functools import partial
from multiprocessing.connection import Connection
from multiprocessing.connection import wait as ready
from multiprocessing.process import BaseProcess
from pathlib import Path
from types import FrameType
from typing import Any, Protocol

from pipeline.stages.contract import Context, Stage, Unit

from .jsonio import digest
from .ledger import Ledger
from .outputs import describe, receipt_digests
from .records import Completion, Output
from .resources import ResourceGuard

# Receipt digests are left to the parent when a worker cannot see every
# recorded inputs hash.
Described = tuple[tuple[Output, ...], dict[str, str] | None]
Result = tuple[int, Described | BaseException]


def run_unit(
    ctx: Context,
    stage: Stage,
    unit: Unit,
    parameters: str,
    hashes: Container[str] | None,
) -> Described:
    """Admit, run and describe one unit; receipts too when `hashes` is known."""
    ctx.guard.admit(unit.required_bytes)
    outputs: tuple[Output, ...] | None = None
    try:
        outputs = describe(ctx.root, stage.run(ctx, unit))
        # Units of one stage may share parameter objects, such as a policy.
        if digest(unit.recipe.parameters) != parameters:
            raise ValueError(
                f"{stage.name}/{unit.recipe.unit_id} changed its recipe "
                "parameters; copy them before editing"
            )
        receipts = (
            None if hashes is None else receipt_digests(ctx.root, outputs, hashes)
        )
        return outputs, receipts
    finally:
        written = None if outputs is None else sum(item.size for item in outputs)
        ctx.guard.release(
            unit.required_bytes,
            written_bytes=0 if unit.accounts_disk else written,
        )
        if unit.accounts_disk:
            ctx.guard.refresh_usage()


class Workers(Protocol):
    def submit(
        self, stage: Stage, unit: Unit, parameters: str, hashes: Container[str]
    ) -> int: ...
    def collect(self) -> list[Result]:
        """Block until at least one unit finished; raise on an interrupt."""
        ...

    def close(self, *, abandon: bool = False) -> None: ...


class ThreadWorkers:
    """Units share this interpreter; Python-heavy units contend for its lock."""

    def __init__(self, ctx: Context, size: int) -> None:
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=size)
        self.futures: dict[Future[Described], int] = {}
        self.tasks = 0

    def submit(
        self, stage: Stage, unit: Unit, parameters: str, hashes: Container[str]
    ) -> int:
        self.tasks += 1
        future = self.pool.submit(run_unit, self.ctx, stage, unit, parameters, hashes)
        self.futures[future] = self.tasks
        return self.tasks

    def collect(self) -> list[Result]:
        done, _ = wait(self.futures, return_when=FIRST_COMPLETED)
        results: list[Result] = []
        for future in done:
            outcome: Described | BaseException
            try:
                outcome = future.result()
            except Exception as error:
                outcome = error
            results.append((self.futures.pop(future), outcome))
        return results

    def close(self, *, abandon: bool = False) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class WorkerDied(RuntimeError):
    """A worker process ended while running a unit, which was not recorded."""


class Channel:
    """A child's end of its pipe: one request at a time, answered in order."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.lock = threading.Lock()

    def tell(self, *message: object) -> None:
        with self.lock:
            self.connection.send(message)

    def ask(self, *message: object) -> Any:
        with self.lock:
            self.connection.send(message)
            return self.connection.recv()


class RemoteLedger(Ledger):
    """Children read records through the parent and never touch SQLite."""

    def __init__(self, root: Path, channel: Channel) -> None:
        self.root, self.path, self.readonly = root, None, True
        self.channel = channel

    def get(self, stage: str, unit_id: str) -> Completion | None:
        record: Completion | None = self.channel.ask("get", stage, unit_id)
        return record


class RemoteGuard(ResourceGuard):
    """Admission stays in the parent, so reservations and memory are global."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def admit(self, required_bytes: int = 0) -> None:
        refusal = self.channel.ask("admit", required_bytes)
        if refusal is not None:
            raise ValueError(refusal)

    def release(self, reserved_bytes: int, *, written_bytes: int | None = None) -> None:
        self.channel.tell("release", reserved_bytes, written_bytes)

    def refresh_usage(self) -> None:
        self.channel.tell("refresh")


def die_with_parent() -> None:
    """Linux sends the child SIGTERM when its parent exits, even by SIGKILL."""
    if sys.platform.startswith("linux"):
        with contextlib.suppress(OSError, AttributeError):
            ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)


def portable(error: BaseException) -> BaseException | None:
    """The error itself when the parent can rebuild it; its text arrives anyway."""
    try:
        pickle.loads(pickle.dumps(error))
    except Exception:
        return None
    return error


def serve(connection: Connection, ctx: Context, stages: dict[str, Stage]) -> None:
    """The child's loop: run units until the parent sends None."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    die_with_parent()
    channel = Channel(connection)
    child = replace(
        ctx,
        ledger=RemoteLedger(ctx.root, channel),
        guard=RemoteGuard(channel),
        log=partial(channel.tell, "log"),
    )
    while (task := connection.recv()) is not None:
        name, unit, parameters = task
        try:
            outcome: tuple[object, ...] = (
                "done",
                run_unit(child, stages[name], unit, parameters, None),
            )
        except BaseException as error:
            outcome = ("failed", portable(error), traceback.format_exc())
        channel.tell(*outcome)


@dataclass
class Worker:
    process: BaseProcess
    connection: Connection
    task: int | None = None
    unit: Unit | None = None
    # A pending admission: bytes, when it was asked, when it last logged.
    admission: tuple[int, float, float] | None = None


def exit_status(code: int | None) -> str:
    if code is None or code >= 0:
        return f"exit status {code}"
    name = signal.Signals(-code).name
    hint = "; the out-of-memory killer sends it" if name == "SIGKILL" else ""
    return f"signal {name}{hint}"


class ProcessWorkers:
    """Units in forked processes, so Python-heavy units use every core."""

    def __init__(
        self,
        ctx: Context,
        stages: Sequence[Stage],
        size: int,
        event: Callable[[str], None],
    ) -> None:
        self.ctx, self.size, self.event = ctx, size, event
        self.stages = {stage.name: stage for stage in stages}
        self.context = multiprocessing.get_context("fork")
        self.workers: list[Worker] = []
        self.tasks = 0
        self.interrupts = self.reported = 0
        self.previous: Any = None
        if threading.current_thread() is threading.main_thread():
            self.previous = signal.signal(signal.SIGINT, self.interrupted)

    def interrupted(self, signum: int, frame: FrameType | None) -> None:
        # The first Ctrl-C is reported between messages; a second one aborts.
        self.interrupts += 1
        if self.interrupts > 1:
            raise KeyboardInterrupt

    def submit(
        self, stage: Stage, unit: Unit, parameters: str, hashes: Container[str]
    ) -> int:
        for idle in [w for w in self.workers if w.task is None]:
            if not idle.process.is_alive():
                idle.process.join()
                idle.connection.close()
                self.workers.remove(idle)
        worker = next((w for w in self.workers if w.task is None), None)
        if worker is None:
            worker = self.start()
        self.tasks += 1
        worker.task, worker.unit = self.tasks, unit
        worker.connection.send((stage.name, unit, parameters))
        return self.tasks

    def start(self) -> Worker:
        if len(self.workers) >= self.size:
            raise ValueError("Every worker process is busy")
        parent, child = self.context.Pipe()
        process = self.context.Process(
            target=serve, args=(child, self.ctx, self.stages), daemon=True
        )
        with warnings.catch_warnings():
            # Imports alone start native pools (OpenBLAS, jemalloc, Arrow), which
            # register fork handlers; this process starts no threads of its own,
            # and children never use its SQLite or DuckDB handles.
            warnings.filterwarnings(
                "ignore", ".*is multi-threaded, use of fork", DeprecationWarning
            )
            process.start()
        child.close()
        worker = Worker(process, parent)
        self.workers.append(worker)
        return worker

    def collect(self) -> list[Result]:
        results: list[Result] = []
        while not results:
            if self.interrupts > self.reported:
                self.reported = self.interrupts
                raise KeyboardInterrupt
            self.admissions()
            busy = [worker for worker in self.workers if worker.task is not None]
            if not busy:
                raise ValueError("No unit is running in a worker process")
            waiting = [w.connection for w in busy] + [w.process.sentinel for w in busy]
            signalled = set(ready(waiting, timeout=0.25))
            for worker in busy:
                if worker.connection in signalled:
                    results.extend(self.receive(worker))
                elif worker.process.sentinel in signalled:
                    results.extend(self.receive(worker))
                    if worker.task is not None:
                        results.append(self.died(worker))
        return results

    def receive(self, worker: Worker) -> list[Result]:
        results = []
        try:
            while worker.task is not None and worker.connection.poll():
                if (
                    result := self.handle(worker, worker.connection.recv())
                ) is not None:
                    results.append(result)
        except (EOFError, OSError):
            if worker.task is not None:
                worker.process.join(5)
                results.append(self.died(worker))
        return results

    def died(self, worker: Worker) -> Result:
        task, unit = worker.task, worker.unit
        assert task is not None and unit is not None
        worker.process.join(5)
        self.workers.remove(worker)
        worker.connection.close()
        name = f"{unit.recipe.stage}/{unit.recipe.unit_id}"
        return task, WorkerDied(
            f"Worker process {worker.process.pid} running {name} ended with "
            f"{exit_status(worker.process.exitcode)}; the unit was not recorded"
        )

    def handle(self, worker: Worker, message: tuple[Any, ...]) -> Result | None:
        kind, *body = message
        guard = self.ctx.guard
        if kind == "log":
            self.event(str(body[0]))
        elif kind == "get":
            worker.connection.send(self.ctx.ledger.get(*body))
        elif kind == "admit":
            # A refusal is logged at once, then at most once per poll interval.
            worker.admission = (int(body[0]), time.monotonic(), float("-inf"))
            self.admit(worker)
        elif kind == "release":
            guard.release(int(body[0]), written_bytes=body[1])
        elif kind == "refresh":
            guard.refresh_usage()
        else:
            task = worker.task
            assert task is not None
            worker.task = worker.unit = None
            if kind == "done":
                described: Described = body[0]
                return task, described
            error, text = body
            error = error or RuntimeError("A unit failed in a worker process")
            error.add_note(f"Worker process traceback:\n{text}")
            return task, error
        return None

    def admissions(self) -> None:
        for worker in self.workers:
            if worker.admission is not None:
                self.admit(worker)

    def admit(self, worker: Worker) -> None:
        assert worker.admission is not None
        required, asked, logged = worker.admission
        guard, now = self.ctx.guard, time.monotonic()
        reason = guard.attempt(required)
        if reason is None:
            worker.admission = None
            worker.connection.send(None)
        elif now - asked >= guard.limits.admission_timeout_seconds:
            worker.admission = None
            worker.connection.send(guard.refusal(now - asked, reason))
        elif now - logged >= guard.limits.poll_seconds:
            worker.admission = (required, asked, now)
            self.event(f"paused on {reason}; waiting for resource headroom")

    def close(self, *, abandon: bool = False) -> None:
        """Stop idle workers; terminate busy ones, which only happens on errors."""
        for worker in self.workers:
            if worker.task is None and not abandon:
                with contextlib.suppress(OSError):
                    worker.connection.send(None)
        for worker in self.workers:
            if worker.task is not None or abandon:
                worker.process.terminate()
            worker.process.join(10)
            if worker.process.is_alive():
                worker.process.kill()
                worker.process.join()
            worker.connection.close()
        self.workers.clear()
        if self.previous is not None:
            signal.signal(signal.SIGINT, self.previous)
            self.previous = None
