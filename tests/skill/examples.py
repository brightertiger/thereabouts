"""Parse and run the fenced examples of a skill document.

A document is prose plus fenced blocks, and every block is either inert or run:

- ``mcp``: the first word is a tool name and the rest is its JSON arguments.
- ``sql``: one DuckDB query over the dataset views held in ``con``.
- ``python``: executed in a namespace shared by the whole run.
- ``json`` directly after an ``mcp`` block: the result must contain this subset.
- ``csv`` directly after a ``sql`` block: the exact rows, header first.
- ``text``: never run, for layout and output.

Any other language is rejected so that no example can silently stay unexecuted.
With ``verify=False`` (a real release, whose contents differ from the fixtures)
every example must still run, but expected results are not compared.
"""

import csv
import io
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUNNABLE = {"mcp", "sql", "python"}
EXPECTATIONS = {"json": "mcp", "csv": "sql"}
INERT = {"text"}

CallTool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class ExampleError(AssertionError):
    """A documented example failed; the message names the file and line."""


@dataclass(frozen=True)
class Example:
    path: Path
    line: int
    language: str
    source: str
    expected: str | None = None

    @property
    def where(self) -> str:
        return f"{self.path.name}:{self.line}"


def blocks(path: Path) -> list[tuple[int, str, str]]:
    """Every fenced block as (first line, language, text)."""
    found: list[tuple[int, str, str]] = []
    lines = path.read_text().splitlines()
    start = 0
    language = ""
    body: list[str] = []
    for number, line in enumerate(lines, 1):
        if line.startswith("```"):
            if start:
                found.append((start, language, "\n".join(body)))
                start, body = 0, []
            else:
                start, language = number, line[3:].strip()
        elif start:
            body.append(line)
    if start:
        raise ExampleError(f"{path.name}:{start}: unterminated code fence")
    return found


def parse(path: Path) -> list[Example]:
    examples: list[Example] = []
    for line, language, text in blocks(path):
        if language in INERT:
            continue
        if language in EXPECTATIONS:
            previous = examples[-1] if examples else None
            if (
                previous is None
                or previous.language != EXPECTATIONS[language]
                or previous.expected is not None
            ):
                raise ExampleError(
                    f"{path.name}:{line}: {language} block must follow "
                    f"a {EXPECTATIONS[language]} block"
                )
            examples[-1] = Example(
                previous.path, previous.line, previous.language, previous.source, text
            )
        elif language in RUNNABLE:
            examples.append(Example(path, line, language, text))
        else:
            raise ExampleError(f"{path.name}:{line}: unrunnable block ({language!r})")
    return examples


def contains(actual: Any, expected: Any) -> bool:
    """Whether `actual` holds everything in `expected`; extra keys are allowed."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(contains(a, e) for a, e in zip(actual, expected, strict=True))
        )
    return bool(actual == expected)


def cell(value: Any) -> str:
    return "" if value is None else str(value)


async def call(example: Example, call_tool: CallTool, verify: bool) -> None:
    found = re.match(r"\s*(\w+)\s*(.*)", example.source, re.DOTALL)
    if found is None:
        raise ExampleError(f"{example.where}: an mcp block starts with a tool name")
    name, arguments = found.group(1), json.loads(found.group(2) or "{}")
    result = await call_tool(name, arguments)
    if not isinstance(result, dict):
        raise ExampleError(f"{example.where}: {name} returned no object")
    if verify and example.expected is not None:
        expected = json.loads(example.expected)
        if not contains(result, expected):
            raise ExampleError(
                f"{example.where}: {name} result differs\n"
                f"expected subset: {json.dumps(expected, indent=1)}\n"
                f"actual: {json.dumps(result, indent=1, default=str)[:3000]}"
            )


def query(example: Example, namespace: dict[str, Any], verify: bool) -> None:
    con = namespace.get("con")
    if con is None:
        raise ExampleError(f"{example.where}: no `con`; run the setup block first")
    relation = con.sql(example.source)
    if relation is None:
        raise ExampleError(f"{example.where}: the query returned no rows object")
    header, rows = list(relation.columns), relation.fetchall()
    if not verify or example.expected is None:
        return
    wanted = list(csv.reader(io.StringIO(example.expected)))
    got = [header, *([cell(v) for v in row] for row in rows)]
    if got != wanted:
        raise ExampleError(
            f"{example.where}: rows differ\nexpected: {wanted}\nactual: {got}"
        )


async def run(
    examples: list[Example],
    call_tool: CallTool,
    namespace: dict[str, Any],
    verify: bool = True,
) -> int:
    """Run in order, sharing `namespace`; returns how many examples ran."""
    for example in examples:
        try:
            if example.language == "mcp":
                await call(example, call_tool, verify)
            elif example.language == "sql":
                query(example, namespace, verify)
            else:
                exec(compile(example.source, example.where, "exec"), namespace)
        except ExampleError:
            raise
        except Exception as error:
            raise ExampleError(
                f"{example.where}: {type(error).__name__}: {error}"
            ) from error
    return len(examples)


async def run_documents(
    paths: list[Path], call_tool: CallTool, dataset: str, verify: bool = True
) -> int:
    """Run each document in its own namespace, where `DATASET` names the release."""
    ran = 0
    for path in paths:
        namespace: dict[str, Any] = {"DATASET": dataset}
        ran += await run(parse(path), call_tool, namespace, verify)
    return ran


def mentions(path: Path) -> list[str]:
    """Tool names used by mcp examples, for coverage checks."""
    names = []
    for example in parse(path):
        if example.language == "mcp":
            found = re.match(r"\s*(\w+)", example.source)
            if found:
                names.append(found.group(1))
    return names
