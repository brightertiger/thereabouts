"""Hash the transitive local import closure without importing production code."""

import ast
import hashlib
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from .watch import WATCH

# The loader and validators only parse and check configuration; every value a
# stage reads is hashed as a declared config section or a unit parameter.
EXCLUDED = (
    "pipeline/runtime/",
    "pipeline/stages/contract.py",
    "pipeline/config/__init__.py",
    "pipeline/config/engine_validation.py",
    "pipeline/config/loader.py",
    "pipeline/config/schema.py",
)


@lru_cache(maxsize=1024)
def imports(module: str, package: bool, source: bytes) -> tuple[str, ...]:
    """Parse bytes rather than caching by mtime, so preserved timestamps are safe."""
    parent = module if package else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = parent.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                name = ".".join(filter(None, (base, node.module)))
            else:
                name = node.module or ""
            names.add(name)
            names.update(f"{name}.{item.name}" for item in node.names)
    return tuple(
        sorted(
            name for name in names if name == "pipeline" or name.startswith("pipeline.")
        )
    )


def code_hashes(packages: Sequence[Path], repository: Path) -> dict[str, str]:
    base = repository / "pipeline"
    root_parts = len(repository.parts)
    base_parts = base.parts
    real_parts = base.resolve().parts
    modules: dict[str, Path] = {}
    for path in base.rglob("*.py"):
        name = ".".join(path.parts[root_parts:]).removesuffix(".py")
        modules[name.removesuffix(".__init__")] = path
    pending = []
    for package in packages:
        if ".." in package.parts or package.parts[: len(base_parts)] != base_parts:
            raise ValueError("Stage code must live under pipeline/")
        candidates = [package] if package.is_file() else sorted(package.rglob("*.py"))
        if not candidates:
            raise ValueError(f"Empty stage code package: {package}")
        pending.extend(candidates)
    result: dict[str, str] = {}
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        if path.suffix != ".py":
            raise ValueError(f"Stage code file must be Python: {path}")
        if path.resolve().parts[: len(real_parts)] != real_parts:
            raise ValueError(f"Stage code symlink escapes pipeline/: {path}")
        name = "/".join(path.parts[root_parts:])
        if name in result or any(name.startswith(item) for item in EXCLUDED):
            continue
        parents = path.parts[root_parts:-1]
        for length in range(1, len(parents) + 1):
            initializer = modules.get(".".join(parents[:length]))
            if initializer is not None and initializer.name == "__init__.py":
                pending.append(initializer)
        source = WATCH.read(path)
        result[name] = hashlib.sha256(source).hexdigest()
        module = name.removesuffix(".py").replace("/", ".")
        is_package = path.name == "__init__.py"
        if is_package:
            module = module.removesuffix(".__init__")
        for imported in imports(module, is_package, source):
            parts = imported.split(".")
            for length in range(1, len(parts) + 1):
                candidate = modules.get(".".join(parts[:length]))
                if candidate is not None:
                    pending.append(candidate)
    return dict(sorted(result.items()))
