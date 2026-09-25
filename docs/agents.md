# Running agents

`scripts/run_agents.py` lets configured agents solve cases, grades every completed
workbook and writes a summary. Agents are defined in
[`configs/agents.toml`](../configs/agents.toml). API keys are read from the environment
variable named in `api_key_env`, never from the file.

## Agent types

| Type | How the agent works | Configured examples |
|---|---|---|
| `cli` | A command-line coding agent runs in an empty temporary folder that holds only `input.xlsx` and `TASK.md`, uses its own tools and saves `output.xlsx`. | `claude-code`, `codex`, `opencode`, `gemini-cli` |
| `chat` | Any OpenAI-compatible `/chat/completions` API. The model receives the instruction and the workbook as text (one line per cell) and replies with JSON cell edits, which are written into a copy of `input.xlsx`. | `gemini-flash`, `gemini-pro`, `openrouter-free`, `groq-llama`, `ollama-qwen` (local, free) |
| `manual` | For chat UIs. `TASK.md` and `input.xlsx` are placed in `results/runs/<run>/<agent>/<case>/`; save the finished workbook there as `output.xlsx` and run the same command again to grade it. | `chatgpt-manual`, `excel-copilot-manual` |

## Commands

```bash
uv run python scripts/run_agents.py --list
uv run python scripts/run_agents.py --agents claude-code gemini-flash --cases data/cases/14_07 data/cases/06_18 --run-id pilot
uv run python scripts/run_agents.py --agents gemini-flash --cases data/cases --run-id full
uv run python scripts/run_agents.py --summarize results/runs/pilot
```

Add `--sensitivity` to name the inputs behind each perturbation failure
([methodology](methodology.md#per-input-diagnosis)).

The smallest real-agent suite runs one agent on three representative cases
(`02_01`, `06_18`, `14_07`) and grades with LibreOffice by default:

```bash
uv run python scripts/run_real_agent_suite.py
uv run python scripts/run_real_agent_suite.py --agents codex gemini-flash --run-id codex-vs-gemini
```

## Outputs

Each run writes `results/runs/<run-id>/<agent>/<case>/` with `output.xlsx`,
`agent_log.json` and `report.json`, plus these files for the run:

- `summary.md` and `summary.json`: value-only grading (all numbers correct, as
  answer-matching benchmarks score) next to Tickmark's verdict, and why each case
  failed.
- `report.html`: one self-contained page in the AAI Labs style, fonts and logo
  embedded, ready to share. It covers the headline gap, right numbers against real
  models per agent, the outcome mix with each agent's strongest domain and weakest
  check, heatmaps of checks, model types and sizes, and every case with its main issue.

Re-running a `--run-id` skips cases that already have a report (use `--rerun` to redo
them), so rate-limited runs can be resumed. If grading fails, for example because the
engine crashes, the case is logged with the error and the run continues; the next run
of the same `--run-id` grades that workbook again without re-running the agent.

## One-off solving

To have an agent fill one case without grading or summaries:

```bash
uv run python scripts/solve_case.py --agent gemini-flash --case data/cases/02_01
uv run python scripts/solve_case.py --agent claude-code --case data/cases/14_07 --output fixed.xlsx
```

It reads `case.json`, gives the agent only the instruction and `input.xlsx`, and writes
the completed workbook.

## OpenCode

The `opencode` adapter uses `opencode/glm-5.2` through an OpenCode Zen account. Its
inline configuration denies web access, subagents and files outside the case folder,
and allows Python for editing the workbook with openpyxl. Confirm the login first:

```bash
opencode auth list
uv run python scripts/run_real_agent_suite.py --agents opencode --run-id opencode-pilot --engine libreoffice
```

## Isolation

`cli` agents run in a temporary folder outside the repository with restricted tools,
but they still run on your machine with your user rights. Use a container for
untrusted agents. Chat models see only the workbook text.
