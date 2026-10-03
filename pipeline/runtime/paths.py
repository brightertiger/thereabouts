"""Keep logical root-relative paths; reject escapes, including through symlinks."""

from pathlib import Path, PurePosixPath


def validate_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or value != path.as_posix()
        or value == "."
    ):
        raise ValueError(f"Not a workspace-relative path: {value}")
    return value


def located(root: Path, value: str) -> Path:
    path = root / validate_relative(value)
    # Resolution is only a containment check; never persist the resolved spelling.
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes workspace through a symlink: {value}")
    return path


def relative(root: Path, path: Path) -> str:
    value = path.absolute().relative_to(root.absolute()).as_posix()
    located(root, value)
    return value
