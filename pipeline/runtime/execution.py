"""Bounded scheduling and explicit restoration of absent direct inputs."""

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace

from pipeline.stages.contract import Context, Stage, Unit, make_unit

from .outputs import describe
from .paths import located
from .planning import decide
from .records import Output
from .watch import WATCH, InputsChanged, changed_message

Described = tuple[tuple[Output, ...], dict[str, str]]


class Executor:
    def __init__(
        self,
        ctx: Context,
        stages: Sequence[Stage],
        event: Callable[[str], None],
    ) -> None:
        self.ctx, self.stages, self.event = ctx, stages, event
        self.by_stage = {stage.name: stage for stage in stages}
        self.cache: dict[str, dict[tuple[str, str], Unit]] = {}
        # Identities are fixed once, before any unit runs: the code a process
        # imported is the code its records describe. Later edits stop the run
        # at the next unit boundary (see `check`).
        self.identities = {stage.name: stage.identity(ctx) for stage in stages}
        self.completed = 0
        self.skipped = 0
        self.skipped_keys: set[tuple[str, str]] = set()
        self.completed_keys: set[tuple[str, str]] = set()

    def skip(self, key: tuple[str, str]) -> None:
        if key not in self.skipped_keys and key not in self.completed_keys:
            self.skipped_keys.add(key)
            self.skipped += 1

    def discover(self, name: str) -> dict[tuple[str, str], Unit]:
        if name not in self.cache:
            units = self.by_stage[name].units(self.ctx)
            self.cache[name] = {unit.key: unit for unit in units}
            if len(self.cache[name]) != len(units):
                raise ValueError(f"Duplicate unit in stage {name}")
        return self.cache[name]

    def identity(self, name: str) -> str:
        return self.identities[name]

    @staticmethod
    def check() -> None:
        if names := WATCH.changed():
            raise InputsChanged(changed_message(names))

    def refresh(self, unit: Unit) -> Unit:
        return replace(
            make_unit(self.ctx, unit.recipe, self.identity(unit.recipe.stage)),
            required_bytes=unit.required_bytes,
            accounts_disk=unit.accounts_disk,
            refresh_discovery=unit.refresh_discovery,
        )

    def missing(self, unit: Unit) -> bool:
        record = self.ctx.ledger.get(*unit.key)
        absent = record.metadata.get("absent_paths", []) if record else []
        return isinstance(absent, list) and any(
            not located(self.ctx.root, str(path)).exists() for path in absent
        )

    def execute(
        self,
        name: str,
        *,
        materialize: bool = False,
        requested: Sequence[Unit] | None = None,
        finalize: bool = True,
    ) -> None:
        with WATCH.frozen():
            self._execute(
                name, materialize=materialize, requested=requested, finalize=finalize
            )

    def _execute(
        self,
        name: str,
        *,
        materialize: bool,
        requested: Sequence[Unit] | None,
        finalize: bool,
    ) -> None:
        self.cache.pop(name, None)
        required: dict[tuple[str, str], Unit] = {}
        visiting: set[tuple[str, str]] = set()
        checked: set[tuple[str, str]] = set()
        prepared: set[str] = set()

        def require(unit: Unit, *, payload: bool) -> None:
            if unit.recipe.stage not in prepared:
                prepared.add(unit.recipe.stage)
                for prerequisite in self.discover(unit.recipe.stage).values():
                    if prerequisite.refresh_discovery and prerequisite.key != unit.key:
                        require(prerequisite, payload=False)
            if unit.key in visiting:
                raise ValueError(f"Unit dependency cycle: {unit.key}")
            if unit.key in required:
                return
            if unit.key in checked and not (payload and self.missing(unit)):
                return
            unit = self.refresh(unit)
            visiting.add(unit.key)
            for dep in unit.recipe.dependencies:
                upstream = self.discover(dep.stage).get(dep.key)
                if upstream is None:
                    raise ValueError(f"Undeclared dependency: {dep.key}")
                require(upstream, payload=False)
            visiting.remove(unit.key)
            checked.add(unit.key)
            changed = any(dep.key in required for dep in unit.recipe.dependencies)
            if (
                not changed
                and decide(self.ctx, unit).state == "current"
                and not (payload and self.missing(unit))
            ):
                self.skip(unit.key)
            else:
                required[unit.key] = unit

        for unit in (
            [self.discover(name)[unit.key] for unit in requested]
            if requested is not None
            else self.discover(name).values()
        ):
            require(unit, payload=materialize)
        for stage in self.stages:
            pending = {
                key: unit for key, unit in required.items() if key[0] == stage.name
            }
            refresh = {
                key: unit for key, unit in pending.items() if unit.refresh_discovery
            }
            if refresh:
                self._stage(stage, refresh)
                self.cache.clear()
                self._execute(
                    name,
                    materialize=materialize,
                    requested=requested,
                    finalize=finalize,
                )
                return
            participated = bool(pending)
            if participated:
                self._stage(stage, pending)
            if (participated or stage.name == name) and (
                finalize or stage.name != name
            ):
                stage.finish(self.ctx)

    def restore_inputs(self, stage: Stage, unit: Unit) -> None:
        for dependency in unit.recipe.dependencies:
            upstream = self.discover(dependency.stage)[dependency.key]
            if self.missing(upstream):
                self.execute(
                    dependency.stage,
                    materialize=True,
                    requested=[upstream],
                    finalize=dependency.stage != stage.name,
                )

    def _stage(self, stage: Stage, pending: dict[tuple[str, str], Unit]) -> None:
        """Run ready units; on a failure, an interrupt or an edit, stop scheduling.

        Running units are always waited for. Those that finish are recorded,
        except after an edit to hashed inputs, when nothing more is recorded.
        A second interrupt abandons the wait.
        """
        running: dict[Future[Described], Unit] = {}
        stop: BaseException | None = None
        pool = ThreadPoolExecutor(max_workers=self.ctx.config.resources.workers)
        try:
            while pending or running:
                if stop is None:
                    try:
                        self._submit(stage, pending, running, pool)
                    except (Exception, KeyboardInterrupt) as error:
                        stop = error
                if not running:
                    if pending and stop is None:
                        raise ValueError("No runnable unit; unresolved dependencies")
                    break
                try:
                    ready, _ = wait(running, return_when=FIRST_COMPLETED)
                except KeyboardInterrupt as error:
                    if isinstance(stop, KeyboardInterrupt):
                        raise
                    stop = error
                    self.event(f"interrupted; waiting for {len(running)} units")
                    continue
                for future in ready:
                    unit = running.pop(future)
                    name = f"{stage.name}/{unit.recipe.unit_id}"
                    try:
                        outputs, receipts = future.result()
                    except Exception as error:
                        self.event(f"failed {name}: {error}")
                        stop = stop or error
                        continue
                    if not isinstance(stop, InputsChanged):
                        try:
                            self.check()
                        except InputsChanged as error:
                            stop = error
                    if isinstance(stop, InputsChanged):
                        self.event(f"not recorded {name}: hashed inputs changed")
                        continue
                    self._record(unit, outputs, receipts)
                    self.event(f"complete {name}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if stop is not None:
            raise stop

    def _submit(
        self,
        stage: Stage,
        pending: dict[tuple[str, str], Unit],
        running: dict[Future[Described], Unit],
        pool: ThreadPoolExecutor,
    ) -> None:
        active = set(pending) | {u.key for u in running.values()}
        for key, original in list(pending.items()):
            if len(running) >= self.ctx.config.resources.workers:
                break
            if any(dep.key in active for dep in original.recipe.dependencies):
                continue
            unit = self.refresh(original)
            if decide(self.ctx, unit).state == "current" and not self.missing(unit):
                del pending[key]
                active.remove(key)
                self.skip(unit.key)
                continue
            missing = any(
                self.missing(self.discover(dep.stage)[dep.key])
                for dep in unit.recipe.dependencies
            )
            if missing:
                if running:
                    continue
                self.restore_inputs(stage, unit)
                unit = self.refresh(unit)
            self.check()
            del pending[key]
            self.event(f"running {stage.name}/{unit.recipe.unit_id}")
            running[pool.submit(self._run, stage, unit)] = unit

    def _record(
        self, unit: Unit, outputs: tuple[Output, ...], receipts: dict[str, str]
    ) -> None:
        with self.ctx.ledger.transaction():
            self.ctx.ledger.register(unit.recipe)
        self.ctx.ledger.record(
            *unit.key,
            unit.inputs_hash,
            outputs,
            receipts,
            metadata={
                "identity": unit.identity,
                "dependency_hash": unit.dependency_hash,
            },
        )
        self.completed += 1
        self.completed_keys.add(unit.key)
        if unit.key in self.skipped_keys:
            self.skipped_keys.remove(unit.key)
            self.skipped -= 1

    def _run(self, stage: Stage, unit: Unit) -> Described:
        """Hash outputs in the worker, so recording stays a short serial step."""
        self.ctx.guard.admit(unit.required_bytes)
        described: Described | None = None
        try:
            described = describe(self.ctx.root, stage.run(self.ctx, unit))
            return described
        finally:
            written = None
            if described is not None:
                written = sum(output.size for output in described[0])
            self.ctx.guard.release(
                unit.required_bytes,
                written_bytes=0 if unit.accounts_disk else written,
            )
            if unit.accounts_disk:
                self.ctx.guard.refresh_usage()
