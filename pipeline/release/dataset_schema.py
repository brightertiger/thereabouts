"""Validate the descriptive metadata config/dataset.yaml carries beside each column.

The loader reads only each column's name, type and nullability. Everything else
feeds the data dictionary, so a typo or a dangling reference is rejected here
instead of reaching a released document. `assembled: true` marks a table or a
trailing column that release assembly computes; release inputs never carry it.
"""

from pathlib import Path
from typing import Any

import yaml

from pipeline.runtime.fingerprints import REPOSITORY

TABLE_REQUIRED = ("description", "grain", "primary_key", "relationships", "columns")
TABLE_KEYS = {*TABLE_REQUIRED, "assembled"}
COLUMN_REQUIRED = ("name", "type", "nullable", "meaning", "units")
COLUMN_KEYS = {*COLUMN_REQUIRED, "values", "values_from", "assembled"}
RELATIONSHIP_KEYS = {"columns", "references", "meaning"}
ENUMERATED = {"string": str, "int64": int, "uint64": int, "uint8": int}


def text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def unknown(where: str, value: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(f"{where}: unknown key {extra[0]}")


def assembled(where: str, value: dict[str, Any]) -> bool:
    flag = value.get("assembled", False)
    if not isinstance(flag, bool):
        raise ValueError(f"{where}: assembled must be a boolean")
    return flag


def column(table: str, value: dict[str, Any], repository: Path) -> None:
    name = value.get("name")
    where = f"{table}.{name}"
    unknown(where, value, COLUMN_KEYS)
    for key in COLUMN_REQUIRED:
        if key not in value:
            raise ValueError(f"{where}: {key} is required")
    if not isinstance(value["nullable"], bool):
        raise ValueError(f"{where}: nullable must be a boolean")
    assembled(where, value)
    values = value.get("values")
    sources = value.get("values_from")
    if sources is not None and values is None:
        raise ValueError(f"{where}: values_from requires values")
    if values is None:
        return
    kind = ENUMERATED.get(value["type"])
    if kind is None:
        raise ValueError(f"{where}: enumerations need a string or integer column")
    if not isinstance(values, list) or not values:
        raise ValueError(f"{where}: values must be a non-empty list")
    seen = set()
    for item in values:
        unknown(where, item, {"value", "meaning"})
        if type(item.get("value")) is not kind:
            raise ValueError(f"{where}: value type does not match the column type")
        if not text(item.get("meaning")):
            raise ValueError(f"{where}: value meaning is required")
        if item["value"] in seen:
            raise ValueError(f"{where}: duplicate enumeration value {item['value']}")
        seen.add(item["value"])
    for path in sources or []:
        if not (repository / path).is_file():
            raise ValueError(f"{where}: source file {path} does not exist")


def relationship(
    table: str, value: dict[str, Any], columns: dict[str, str], tables: dict[str, Any]
) -> None:
    unknown(table, value, RELATIONSHIP_KEYS)
    if not text(value.get("meaning")):
        raise ValueError(f"{table}: relationship meaning is required")
    target = value.get("references") or {}
    unknown(table, target, {"table", "columns"})
    if target.get("table") not in tables:
        raise ValueError(f"{table}: relationship references unknown table")
    remote = {c["name"]: c["type"] for c in tables[target["table"]]["columns"]}
    local, other = value.get("columns") or [], target.get("columns") or []
    if not local or len(local) != len(other):
        raise ValueError(f"{table}: relationship column arity differs")
    for mine, theirs in zip(local, other, strict=True):
        if mine not in columns or theirs not in remote:
            raise ValueError(f"{table}: relationship names unknown column")
        if columns[mine] != remote[theirs]:
            raise ValueError(f"{table}: relationship column type differs: {mine}")
    if other != tables[target["table"]]["primary_key"]:
        raise ValueError(
            f"{table}: relationship must reference the key of {target['table']}"
        )


def check(description: dict[str, Any], repository: Path = REPOSITORY) -> None:
    """Raise ValueError naming the table and column of the first violation."""
    for name, table in description.items():
        unknown(name, table, TABLE_KEYS)
        for key in ("description", "grain"):
            if not text(table.get(key)):
                raise ValueError(f"{name}: {key} is required")
        for key in ("primary_key", "relationships", "columns"):
            if not isinstance(table.get(key), list):
                raise ValueError(f"{name}: {key} must be a list")
        assembled(name, table)
        for item in table["columns"]:
            column(name, item, repository)
        # Appended columns keep every input column at its position.
        computed = [assembled(name, item) for item in table["columns"]]
        if computed != sorted(computed):
            raise ValueError(
                f"{name}: assembled columns must follow every input column"
            )
        columns = {c["name"]: c["type"] for c in table["columns"]}
        if len(columns) != len(table["columns"]):
            raise ValueError(f"{name}: duplicate column name")
        for key in table["primary_key"]:
            if key not in columns:
                raise ValueError(f"{name}: primary key {key} is not a column")
        for item in table["relationships"]:
            relationship(name, item, columns, description)


def load(path: Path, repository: Path = REPOSITORY) -> dict[str, Any]:
    """Read config/dataset.yaml and reject metadata that does not validate."""
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict) or not value:
        raise ValueError("Dataset schema must declare its tables")
    check(value, repository)
    return value


def inputs(description: dict[str, Any]) -> dict[str, Any]:
    """The tables and columns release inputs carry: all but what assembly computes."""
    return {
        name: {
            **table,
            "columns": [c for c in table["columns"] if not c.get("assembled")],
        }
        for name, table in description.items()
        if not table.get("assembled")
    }


def public(description: dict[str, Any]) -> dict[str, Any]:
    """The schema without repository paths, safe to embed in a released manifest."""
    return {
        name: {
            **table,
            "columns": [
                {key: value for key, value in column.items() if key != "values_from"}
                for column in table["columns"]
            ],
        }
        for name, table in description.items()
    }
