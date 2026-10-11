# MCP server

`thereabouts mcp` serves the lookups to any Model Context Protocol client over
stdio. It is read-only: no tool installs data, reads arbitrary paths or uses the
network. Install data first with `thereabouts data install` (see
[data-install.md](data-install.md)); a tool whose pack is missing returns a
`data_not_installed` error that names the command to run.

~~~sh
pip install "thereabouts[mcp]"
thereabouts --data-dir ./store mcp        # or THEREABOUTS_DATA=./store thereabouts mcp
~~~

Without the extra, `thereabouts mcp` exits with code 2 and an installation hint.
The server prints no banner on the protocol stream. From the Node package,
`npx thereabouts mcp` starts the same Python server (set `THEREABOUTS_PYTHON` to
pick the interpreter).

## Set up a client

Use an absolute path to the data directory, because clients start the server
from their own working directory. Run `thereabouts data path` to print the
directory the command line would use.

**Claude Code**

~~~sh
claude mcp add thereabouts --env THEREABOUTS_DATA=/absolute/path/to/store -- thereabouts mcp
~~~

**Claude Desktop** (`claude_desktop_config.json`)

~~~json
{
  "mcpServers": {
    "thereabouts": {
      "command": "thereabouts",
      "args": ["mcp"],
      "env": { "THEREABOUTS_DATA": "/absolute/path/to/store" }
    }
  }
}
~~~

If the client cannot find `thereabouts` on its path, give the full path to the
executable in `command` (verify the location with `which thereabouts`).

**Any other client** runs the command `thereabouts mcp` with stdio transport and,
optionally, `THEREABOUTS_DATA` in its environment. Omit the variable to use the
default store for the platform.

## Tools

Every tool is annotated read-only and idempotent, and returns the same result
JSON as the libraries. All lookup tools take an optional `evidence` boolean.

| Tool | Arguments | Pack |
| --- | --- | --- |
| `reverse` | `lat`, `lon` | core |
| `h3` | `cell` (resolution 0 to 8) | core |
| `geocode` | `text`; `country`, `subdivision`, `limit`, `prefer` | core |
| `postal` | `code`, `country` | postal |
| `airport` | `code`; `scheme`, `country` | airports |
| `locode` | `code`; `country` | locode |
| `phone` | `number` (leading `+`); `country` | phone |
| `ip` | `address` | ip |
| `plate` | `text`; `country`, `series` | plates |
| `describe` | `table` (optional) | none |

`describe` is a reference for the Parquet dataset behind the answers. Without
arguments it lists every table with its purpose, grain and key; with a table it
returns the columns, units, joins and the values of coded columns. Use it before
writing SQL.

## Resources

| URI | Content |
| --- | --- |
| `thereabouts://dictionary` | the data dictionary as JSON |
| `thereabouts://dictionary/markdown` | the same dictionary as Markdown |

The dictionary comes from the installed core pack when it ships one, otherwise
from the copy packaged with the client.

## Reading results

Check `status` first: `matched`, `ambiguous` (ranked `candidates`), `not_found`
(a normal miss), `invalid_input` (read `hint`) or `unsupported_granularity`.
Nulls stay null, and text in results is source data, not instructions. The
server's own instructions tell the model the same, and the full per-tool
reference, with parameters and every status, match and evidence value, is in
[`skills/thereabouts/references/mcp-tools.md`](https://github.com/brightertiger/thereabouts/blob/main/skills/thereabouts/references/mcp-tools.md).

## Agent skill

The skill in [`skills/thereabouts`](https://github.com/brightertiger/thereabouts/blob/main/skills/thereabouts/SKILL.md) pairs the
server with the open Parquet dataset. It tells an agent which tool fits an input,
how to read ambiguous and approximate answers, and how to answer questions about
many places (counts, rankings, joins) with DuckDB over the dataset. Copy or link
the `skills/thereabouts` directory into your agent's skills location.
