"""Every example in the skill documents runs against the fixture packs and dataset."""

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from pipeline.release import dictionary
from pipeline.runtime.fingerprints import REPOSITORY
from tests.skill import examples
from tests.skill.dataset import build
from thereabouts import Geocoder
from thereabouts.mcp_service.server import create_server

SKILL = REPOSITORY / "skills/thereabouts"
HANDWRITTEN = [SKILL / "SKILL.md", SKILL / "references/query-recipes.md"]
PACKS = REPOSITORY / "tests/fixtures/packs"
FAMILIES = ("core", "postal", "airports", "locode", "phone", "ip", "plates")


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory.mktemp("dataset"))


async def execute(dataset: Path, paths: list[Path], verify: bool) -> int:
    """Run each document in its own namespace; the world test reuses this shape."""
    packs = {name: PACKS / f"{name}-sample" for name in FAMILIES}
    with Geocoder(packs=packs) as geo:
        async with Client(create_server(geo)) as client:

            async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                result = await client.call_tool(name, arguments)
                assert not result.is_error, f"{name} {arguments}: {result.content}"
                assert result.structured_content is not None
                return dict(result.structured_content)

            ran = await examples.run_documents(paths, call_tool, str(dataset), verify)
    return ran


@pytest.mark.parametrize("verify", [True, False], ids=["fixtures", "unverified"])
def test_every_example_runs(dataset: Path, verify: bool) -> None:
    ran = asyncio.run(execute(dataset, HANDWRITTEN, verify))
    assert ran >= 30


def test_the_skill_exercises_every_lookup_tool_and_describe() -> None:
    used = {name for path in HANDWRITTEN for name in examples.mentions(path)}
    tools = {tool["name"] for tool in dictionary.build()["tools"]}
    assert tools <= used, sorted(tools - used)


def test_the_skill_shows_every_status_and_the_nearest_matches() -> None:
    text = (SKILL / "SKILL.md").read_text()
    for status in dictionary.build()["results"]["status"]:
        assert f'"status": "{status["value"]}"' in text, status["value"]
    for value in ("nearest_distant", "fuzzy", "contained"):
        assert f'"match": "{value}"' in text


def test_front_matter_triggers_on_the_documented_questions() -> None:
    text = (SKILL / "SKILL.md").read_text()
    front = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", text)
    assert front is not None
    name, description = front.groups()
    assert name == "thereabouts"
    assert len(description) <= 1024
    for phrase in (
        "offline",
        "reverse geocoding",
        "geocoding",
        "postal",
        "airport",
        "LOCODE",
        "IP",
        "phone",
        "plate",
        "DuckDB",
    ):
        assert phrase.lower() in description.lower(), phrase


def test_local_links_resolve() -> None:
    for path in [SKILL / "SKILL.md", *HANDWRITTEN]:
        for target in re.findall(r"`(references/[\w.-]+\.md)`", path.read_text()):
            assert (SKILL / target).is_file(), target


def test_generated_references_are_current() -> None:
    generated = dictionary.outputs()
    for name in ("tables.md", "mcp-tools.md"):
        relative = f"skills/thereabouts/references/{name}"
        assert (REPOSITORY / relative).read_text() == generated[relative]


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doc.md"
    path.write_text(text)
    return path


def lines(*parts: str) -> str:
    return "\n".join(parts) + "\n"


async def stub(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"status": "matched", "echo": [name, arguments], "extra": 1}


def test_parse_pairs_expectations_and_skips_inert_blocks(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        lines(
            "intro",
            "```text",
            "not run",
            "```",
            "```mcp",
            "reverse",
            '{"lat": 1}',
            "```",
            "```json",
            '{"status": "matched"}',
            "```",
            "```sql",
            "select 1 as one",
            "```",
            "```csv",
            "one",
            "1",
            "```",
        ),
    )
    parsed = examples.parse(path)
    assert [e.language for e in parsed] == ["mcp", "sql"]
    assert parsed[0].expected == '{"status": "matched"}' and parsed[0].line == 5
    assert parsed[1].expected == "one\n1"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (lines("```json", "{}", "```"), "json block must follow a mcp block"),
        (lines("```mcp", "h3", "```", "```csv", "a", "```"), "csv block must follow"),
        (lines("```bash", "ls", "```"), "unrunnable block"),
        (lines("```python", "x = 1"), "unterminated code fence"),
        (
            lines(
                "```mcp", "h3", "```", "```json", "{}", "```", "```json", "{}", "```"
            ),
            "json block must follow",
        ),
    ],
)
def test_parse_rejects_blocks_that_could_stay_unexecuted(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(examples.ExampleError, match=message):
        examples.parse(write(tmp_path, text))


def test_contains_allows_extra_keys_but_not_missing_or_different_ones() -> None:
    actual = {"a": {"b": 1, "c": 2}, "d": [1, {"e": 3, "f": 4}]}
    assert examples.contains(actual, {"a": {"b": 1}, "d": [1, {"e": 3}]})
    assert not examples.contains(actual, {"a": {"b": 2}})
    assert not examples.contains(actual, {"missing": None})
    assert not examples.contains(actual, {"d": [1]})


def run_text(tmp_path: Path, text: str, verify: bool = True) -> int:
    parsed = examples.parse(write(tmp_path, text))
    return asyncio.run(examples.run(parsed, stub, {}, verify))


def test_a_wrong_expectation_names_the_file_and_line(tmp_path: Path) -> None:
    text = lines(
        "x", "```mcp", 'h3 {"cell": "1"}', "```", "```json", '{"status": "no"}', "```"
    )
    with pytest.raises(examples.ExampleError, match=r"doc\.md:2: h3 result differs"):
        run_text(tmp_path, text)
    assert run_text(tmp_path, text, verify=False) == 1


def test_sql_rows_are_compared_and_python_errors_are_located(tmp_path: Path) -> None:
    setup = lines("```python", "import duckdb", "con = duckdb.connect()", "```")
    good = lines(
        "```sql", "select 1 as a, 'x' as b", "```", "```csv", "a,b", "1,x", "```"
    )
    assert run_text(tmp_path, setup + good) == 2
    bad = good.replace("1,x", "2,x")
    with pytest.raises(examples.ExampleError, match=r"doc\.md:\d+: rows differ"):
        run_text(tmp_path, setup + bad)
    with pytest.raises(examples.ExampleError, match=r"doc\.md:1: NameError"):
        run_text(tmp_path, lines("```python", "undefined_name", "```"))
    with pytest.raises(examples.ExampleError, match="no `con`"):
        run_text(tmp_path, good)


def iterate(paths: list[Path]) -> Iterator[int]:
    return (len(examples.parse(path)) for path in paths)


def test_the_documents_hold_enough_examples() -> None:
    assert min(iterate(HANDWRITTEN)) >= 10
