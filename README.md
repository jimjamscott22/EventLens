# EventLens
EventLens is a Python command-line tool that reads Windows event logs and power diagnostics and turns them into a plain-English report of what went wrong on a machine.

See [SPEC.md](SPEC.md) for the design, the v1 scope, and the roadmap.

## Usage

Install [uv](https://docs.astral.sh/uv/), clone this repo, then try it on the included sample week:

```bash
uv run eventlens --file examples/sample_week.xml
```

```
Verdict: Serious problems found.
This PC shut down unexpectedly 4 times, including 3 blue screen crashes.

---------------------------------------------------------------------------
CRITICAL  Blue screen crash                       3 times, last 6 Oct 21:02
---------------------------------------------------------------------------
Stop codes:     3x DRIVER_POWER_STATE_FAILURE (0x9F): a driver failed
                   during sleep or wake
...
```

On a Windows PC, run it with no arguments to check the live System and Application logs for the last 7 days:

```bash
uv run eventlens
```

Useful options:

| Option | What it does |
| --- | --- |
| `--file PATH` | Read an exported `.evtx` or `.xml` log (repeat to combine several) |
| `--days N` | Look at the last N days (default 7). For files, counted back from the newest event. |
| `--include-warnings` | Also list warnings EventLens doesn't recognise yet |
| `--utc` | Show times in UTC |
| `--verbose` | Show the latest raw event behind each finding |

Run `uv run eventlens --help` for every option.

Reports can include the computer name, app names, and file paths, so check them before sharing. EventLens only reads logs and never connects to the internet.

## Supported inputs

| Input | Windows | macOS / Linux |
| --- | --- | --- |
| Exported `.evtx` log files | Yes | Yes |
| Event Viewer `.xml` exports | Yes | Yes |
| Live event logs (System, Application) | Yes | No |

So you can export a log on a Windows machine (Event Viewer → *Save All Events As…*) and analyse it anywhere.

## Development

EventLens uses [uv](https://docs.astral.sh/uv/) and needs Python 3.11 or newer.

```bash
uv sync           # create the virtual environment and install dependencies
uv run pytest     # run the test suite
uv run ruff check # check code style
```

Tests run on Windows, macOS, and Linux in CI.
