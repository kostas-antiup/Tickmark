# Contributing

Issues and pull requests are welcome: new cases, agent adapters, grader improvements and
bug reports. Bug reports and case proposals have issue templates. Report security problems
privately, as [SECURITY.md](SECURITY.md) describes.

## Setup

```bash
uv sync --dev --extra audit
uv run pytest tests
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

Python 3.14, Ruff (line length 100), `ty` for types, pytest with PyHamcrest assertions.
Tests that need Microsoft Excel or LibreOffice are marked `excel` or `libreoffice` and
skipped when the engine is missing; CI runs the LibreOffice ones.

## Adding a case

A case is a folder under `data/cases/<id>/` with `input.xlsx`, `golden.xlsx` and
`case.json` (fields in [data/cases/README.md](data/cases/README.md)). The reference must
itself be a clean model:

- `input.xlsx` equals `golden.xlsx` except for blank target cells;
- every target in the golden is a live formula that traces to numeric input cells, with no
  cycles, volatile or iterative functions in the chain;
- every assumption the golden uses is an input cell or stated on the sheet;
- the final output is non-zero and changes when the `input_change_check` input changes.

Then add the case to `index.json` and confirm that the golden passes its own case and that
every generated broken variant fails:

```bash
uv run python scripts/run_benchmark.py --case data/cases/<id> --golden
uv run python scripts/generate_malformed_outputs.py --case data/cases/<id> --output-root results/malformed
uv run python scripts/run_benchmark.py --case data/cases/<id> --malformed-root results/malformed
uv run python scripts/evaluate_malformed_results.py --malformed-root results/malformed --reports-root results
```

Keep the answers out of agent workspaces: only `input.xlsx` and the instruction may be
shown to an agent.

## Adding an agent

Add an `[agents.<name>]` table to [configs/agents.toml](configs/agents.toml) with type
`cli`, `chat` or `manual` ([docs/agents.md](docs/agents.md)). Never commit API keys;
`api_key_env` names the environment variable to read.

## Pull requests

Keep changes focused, add tests for new behaviour, and make sure all four checks above
pass. Generated results stay out of Git (`results/` is ignored).
