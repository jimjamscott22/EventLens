# EventLens
EventLens is a Python command-line tool that reads Windows event logs and power diagnostics and turns them into a plain-English report of what went wrong on a machine.

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
```

Tests run on Windows, macOS, and Linux in CI.
