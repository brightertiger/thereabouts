"""Facts about the public API that the dictionary reads from code instead of copying.

The Rust core spells result statuses, kinds and matches as enums with doc
comments; the Python client declares the result fields and error codes; the MCP
server registers its own tools. Each is read where it is defined, so a change
there changes the generated dictionary and fails the drift check.
"""

import asyncio
import dataclasses
import inspect
import re
import types
from pathlib import Path
from typing import Any, Union, cast, get_args, get_origin, get_type_hints

Row = dict[str, Any]

# Rust declares this field as an untyped JSON value.
JSON_SHAPES = {("Evidence", "source_ids"): "array of objects or null"}
SCALARS = {str: "string", int: "integer", float: "number", bool: "boolean"}
SCHEMA_TYPES = {"string": "string", "number": "number", "integer": "integer"}
SCHEMA_TYPES |= {"boolean": "boolean", "null": "null", "array": "array"}


def sentence(lines: list[str]) -> str:
    return " ".join(lines).strip().removesuffix(".")


def block(text: str, header: str, name: str, source: Path) -> str:
    found = re.search(rf"{header} {name} \{{\n(.*?)\n\}}", text, re.DOTALL)
    if found is None:
        raise ValueError(f"{source.name}: no {header} {name}")
    return found.group(1)


def rust_enum(source: Path, name: str) -> list[Row]:
    """Variants in declaration order with their JSON spelling and doc comment."""
    text = source.read_text()
    docs: dict[str, str] = {}
    pending: list[str] = []
    for line in block(text, "pub enum", name, source).splitlines():
        line = line.strip()
        if line.startswith("///"):
            pending.append(line[3:].strip())
        elif variant := re.fullmatch(r"(\w+),", line):
            docs[variant.group(1)] = sentence(pending)
            pending = []
    spellings = dict(
        re.findall(r'Self::(\w+) => "(\w+)"', block(text, "impl", name, source))
    )
    if set(spellings) != set(docs):
        raise ValueError(f"{name}: as_str does not cover every variant")
    return [{"value": spellings[v], "meaning": docs[v]} for v in docs]


def rust_struct(source: Path, name: str) -> dict[str, str]:
    """Field names (without any r# prefix) mapped to their doc comments."""
    docs: dict[str, str] = {}
    pending: list[str] = []
    for line in block(source.read_text(), "pub struct", name, source).splitlines():
        line = line.strip()
        if line.startswith("///"):
            pending.append(line[3:].strip())
        elif field := re.match(r"pub (?:r#)?(\w+):", line):
            docs[field.group(1)] = sentence(pending)
            pending = []
    return docs


def schema_type(schema: Row) -> str:
    """A JSON-schema property as plain words, such as "string or null"."""
    options = schema.get("anyOf") or [schema]
    return " or ".join(SCHEMA_TYPES[option["type"]] for option in options)


def mcp_tools() -> list[Row]:
    """Registered tools, as the server announces them, in registration order."""
    from thereabouts.geocoder import Geocoder
    from thereabouts.mcp_service.server import create_server

    # Registering tools never touches the geocoder, so no data is needed.
    server = create_server(cast(Geocoder, None))
    tools = []
    for tool in asyncio.run(server.list_tools()):
        required = set(tool.input_schema.get("required", []))
        parameters = []
        for name, schema in tool.input_schema.get("properties", {}).items():
            parameter = {
                "name": name,
                "type": schema_type(schema),
                "required": name in required,
                "description": schema.get("description", ""),
            }
            if name not in required:
                parameter["default"] = schema.get("default")
            parameters.append(parameter)
        tools.append(
            {
                "name": tool.name,
                "description": inspect.cleandoc(tool.description or ""),
                "read_only": bool(tool.annotations and tool.annotations.read_only_hint),
                "parameters": parameters,
            }
        )
    return tools


def mcp_resources() -> list[Row]:
    from thereabouts.geocoder import Geocoder
    from thereabouts.mcp_service.server import create_server

    server = create_server(cast(Geocoder, None))
    return [
        {
            "uri": str(item.uri),
            "title": item.title,
            "mime_type": item.mime_type,
            "description": item.description,
        }
        for item in asyncio.run(server.list_resources())
    ]


def describe_type(hint: Any) -> str:
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        options = get_args(hint)
        words = [describe_type(o) for o in options if o is not type(None)]
        if type(None) in options:
            words.append("null")
        return " or ".join(words)
    if origin is tuple:
        return f"array of {describe_type(get_args(hint)[0])}"
    if hint in SCALARS:
        return SCALARS[hint]
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        return hint.__name__
    raise ValueError(f"Unsupported result field type: {hint!r}")


def field_docs(cls: type, docs: dict[str, str]) -> list[Row]:
    hints = get_type_hints(cls)
    return [
        {
            "name": field.name,
            "type": JSON_SHAPES.get((cls.__name__, field.name))
            or describe_type(hints[field.name]),
            "meaning": docs[field.name],
        }
        for field in dataclasses.fields(cls)
    ]


def result_shape(repository: Path) -> Row:
    """The Python result dataclasses documented with the Rust field comments."""
    from thereabouts import results

    source = repository / "core/thereabouts-core/src/result.rs"
    names = ["Country", "State", "City", "Point", "DistanceBand", "Evidence"]
    return {
        "fields": field_docs(results.Result, rust_struct(source, "LookupResult")),
        "objects": {
            name: field_docs(getattr(results, name), rust_struct(source, name))
            for name in names
        },
    }


def error_codes() -> list[Row]:
    """Stable error code strings from the client's own error module."""
    from thereabouts import errors

    pending = [errors.GeocoderError]
    found: dict[str, str] = {}
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__ == errors.__name__:
            doc = (cls.__doc__ or "").strip().splitlines()[0]
            found[cls.code] = doc.removesuffix(".")
    return [{"code": code, "meaning": found[code]} for code in sorted(found)]
