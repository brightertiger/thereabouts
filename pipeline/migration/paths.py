"""Translate historical workspace prefixes without following the old symlink."""

from pathlib import Path

from pipeline.runtime.jsonio import JSON
from pipeline.runtime.paths import validate_relative

# Only known historical workspace roots are recognized. Unknown absolute paths
# fail migration instead of being silently made relative to the current machine.
WORKSPACE_DIRECTORIES = {
    "raw",
    "normalized",
    "reconciled",
    "city_normalized",
    "base_cells",
    "golden",
    "golden-v1",
    "golden-v2",
    "golden-thereabouts",
    "golden-base-thereabouts",
    "work",
}


def legacy_relative(value: str, root: Path) -> str:
    if not value.startswith("/"):
        return value
    prefix = str(root.absolute()).rstrip("/") + "/"
    if value.startswith(prefix):
        return validate_relative(value[len(prefix) :])
    _, separator, tail = value.rpartition("/data/")
    if separator and tail.split("/", 1)[0].split(":", 1)[0] in WORKSPACE_DIRECTORIES:
        return validate_relative(tail)
    raise ValueError(f"Unrecognized absolute workspace path: {value}")


def portable(
    value: JSON,
    root: Path,
    aliases: dict[str, str] | None = None,
    *,
    key: str = "",
) -> JSON:
    aliases = aliases or {}
    if isinstance(value, str):
        if value in aliases:
            return aliases[value]
        if value.startswith(str(root.absolute()).rstrip("/") + "/") or (
            value.startswith("/") and "/data/" in value
        ):
            converted = legacy_relative(value, root)
            return aliases.get(converted, converted)
        # Overture audit records contain JSON pointers, not filesystem paths.
        if (
            value.startswith("/")
            and key in {"path", "base_manifest", "output", "root"}
            and not value.startswith("/properties/")
        ):
            raise ValueError(f"Unrecognized absolute artifact path: {value}")
        return aliases.get(value, value)
    if isinstance(value, list):
        return [portable(item, root, aliases, key=key) for item in value]
    if isinstance(value, dict):
        return {
            str(portable(name, root, aliases)): portable(item, root, aliases, key=name)
            for name, item in value.items()
        }
    return value
