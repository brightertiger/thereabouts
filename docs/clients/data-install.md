# Installing data

No client bundles geographic data. You install it once with an explicit
command, and every later lookup reads local files. Python, Node and the native
command line share one installer, one store and one set of rules.

~~~sh
thereabouts data install core postal airports
thereabouts data list
thereabouts info
~~~

Use `npx thereabouts ...` for the Node package. The full command grammar is in
[cli.md](cli.md).

## Families

| Family | Answers |
| --- | --- |
| `core` | reverse, H3 cells, city names, timezones |
| `postal` | postal codes |
| `airports` | airport codes |
| `locode` | UN/LOCODE |
| `phone` | phone calling-code prefixes |
| `ip` | IPv4 and IPv6 addresses |
| `plates` | vehicle plate formats |

All installed families share one dataset version. Installing more families at
the active version keeps the others; moving to another version needs every
active family in the same request. A forward family installed with `core`
returns canonical city and timezone detail.

## Sources

By default packs come from this project's GitHub Releases
(`https://github.com/brightertiger/thereabouts/releases/latest/download/`).

| Choice | How |
| --- | --- |
| Another source for one install | `--from DIR_OR_URL` |
| Another source for install, `data list --remote` and `data update --check` | `THEREABOUTS_RELEASE_URL` |
| A specific dataset version | `--version V` |

A source is a directory, or an HTTP(S) base URL, that holds `index.json` and the
archives it lists. A directory of files downloaded from a GitHub release works
as a source.

While the repository is private, set `THEREABOUTS_RELEASE_TOKEN` (or
`GITHUB_TOKEN`) to a token that can read its contents. The token is sent only to
the GitHub API origin and never across a redirect, and only for GitHub-shaped
release URLs. Once the repository is public, no token is needed.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `THEREABOUTS_DATA` | data directory; `--data-dir` overrides it |
| `THEREABOUTS_RELEASE_URL` | default release source |
| `THEREABOUTS_RELEASE_TOKEN`, `GITHUB_TOKEN` | read access to a private release repository |
| `THEREABOUTS_GITHUB_API_URL` | alternative API origin for GitHub Enterprise or tests |
| `THEREABOUTS_PYTHON` | Python used by `npx thereabouts mcp` |

## Store layout

The data directory is `--data-dir`, then `THEREABOUTS_DATA`, then the platform
default.

| Platform | Default |
| --- | --- |
| macOS | `~/Library/Application Support/Thereabouts` |
| Linux | `$XDG_DATA_HOME/thereabouts`, otherwise `~/.local/share/thereabouts` |
| Windows | `%LOCALAPPDATA%/Thereabouts` |

~~~text
<data-dir>/
  active.json                      the pointer to the active version of each family
  .lock                            held during install and remove
  .downloads/                      resumable partial archives
  .staging/                        archives being unpacked
  packs/<family>/<version>/        one installed pack
  dataset/<version>/               the Parquet dataset, when installed
~~~

`active.json` is authoritative: a family it omits counts as not installed even if
an older version is still on disk. Treat installed pack files as immutable.

## Commands

| Command | Does |
| --- | --- |
| `data install PACK... [--version V] [--from SRC]` | download, verify and activate packs |
| `data install dataset [--version V] [--from SRC]` | restore the Parquet dataset |
| `data list [--remote]` | local inventory, or the releases available |
| `data update --check` | compare the active version with the release index |
| `data verify [--full]` | check sizes, or every hash with `--full` |
| `data remove PACK [--yes]` | remove a family |
| `data path` | print the resolved data directory |
| `info` | installed data identities and capabilities |

An install checks every archive's size and SHA-256, unpacks into staging, and
writes `active.json` atomically only after everything verified. A failed
install keeps the previous version. Interrupted downloads resume from the
partial file on the next explicit install. Archives are extracted with strict
path rules, so a hostile archive cannot write outside the store.

The dataset is a separate, larger download (about 2.6 GB for the first world
release). It restores to `dataset/<version>/` after reserving the space needed,
checks every file against the manifest, and moves the tree into place only when
complete. An existing version is verified, never overwritten.

## Offline guarantee

Opening a geocoder, running a lookup and starting the MCP server never contact
the network and never install anything. A missing pack raises or reports
`data_not_installed` with the exact command to run. Only `data install`,
`data list --remote` and `data update --check` use the network.

## Troubleshooting

- **Another install is running (exit 2).** Two installers share one store. Wait
  for the first to finish.
- **A stale lock after a crash.** Dead owners are recovered automatically. If the
  operating system reused the dead installer's process id, the lock can look
  live. Confirm no install is running, then delete `<data-dir>/.lock`.
- **Corrupt or incompatible data.** Run `thereabouts data verify --full`, then
  reinstall the family.
