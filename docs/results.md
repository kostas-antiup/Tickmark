# Results

All numbers on this page come from the commands under [Reproduce](#reproduce), run on
Windows 11 with Microsoft Excel as the recalculation engine (25 September 2026). CI
repeats the reference self-test and part of the broken-workbook regression with
LibreOffice on every push.

## Reference self-test

Every reference workbook (`golden.xlsx`) is graded against its own case.

| Grader | Reference workbooks passed |
|---|---:|
| Tickmark | 35 / 35 |
| SpreadsheetBench rule | 35 / 35 |
| SheetCopilot rule | 35 / 35 |

Grading all 35 took 3 min 16 s with Excel, including the fixed and branch-seeking
input scenarios for every case.

## Broken workbooks

`generate_malformed_outputs.py` breaks each reference model in seven controlled ways,
245 workbooks in total. Each variant is graded like an agent submission, and each
existing grader's rule is applied to the same recalculated file. A workbook is caught when
the grader fails it.

| Variant | What changes | SpreadsheetBench rule | SheetCopilot rule | Tickmark |
|---|---|---:|---:|---:|
| `hardcoded_final` | final output pasted as its correct value | 0 / 35 | 0 / 35 | 35 / 35 |
| `hardcoded_half` | half of the targets pasted as values | 0 / 35 | 0 / 35 | 35 / 35 |
| `hardcoded_all` | every target pasted as a value | 0 / 35 | 0 / 35 | 35 / 35 |
| `hardcoded_intermediate` | one formula feeding the final output pasted as a value | 0 / 35 | 0 / 35 | 35 / 35 |
| `fake_formula_final` | final output written as a constant formula, e.g. `=9080487` | 0 / 35 | 0 / 35 | 35 / 35 |
| `wrong_formula_final` | final formula keeps its references but is 1% (plus one) too high | 35 / 35 | 35 / 35 | 35 / 35 |
| `broken_reference_final` | final output points to a sheet that does not exist | 35 / 35 | 35 / 35 | 35 / 35 |
| **All caught** | | **70 / 245** | **70 / 245** | **245 / 245** |

The existing rules catch only the variants with wrong numbers and miss all 175 whose
numbers stay right; Tickmark catches all 245. The disagreement runs one way only: no
workbook is caught by an existing rule and missed by Tickmark. Each variant's manifest also predicts its value, formula-coverage and
traceability scores; all 245 reports matched those predictions on all three scores
(`evaluate_malformed_results.py`). Grading the 245 workbooks took 12 min 12 s with Excel.

## A hidden constant

A submission for case `14_07` (rent roll) with every target filled by a formula
([`examples/14_07-hidden-constant.xlsx`](../examples/14_07-hidden-constant.xlsx)):

```text
RentRoll!G20  =C20+D20+E20+1161600
```

| Check | Result |
|---|---|
| Correct values | pass, 20 / 20 |
| Formula coverage | pass, 20 / 20 |
| Traceability | pass, 20 / 20 |
| No hardcoded values, no fake formulas | pass |
| Input change (`C7` +10%) | pass: `G20` moves exactly as the reference does |
| Perturbation | **fail**: `G20` diverges from the reference in the up, down, mixed and switches scenarios |
| SpreadsheetBench rule / SheetCopilot rule | both pass the workbook, so both miss the constant |

`1161600` is the 3-Bed column total (`F20`) pasted as a number. Changing a Studio input
still moves `G20` correctly, which is why a single input-change test is not enough; the
scenarios change every input at once. The report's input-footprint warning names the
ignored inputs: `F7`, `F10`, `F12`, `F14` and `F16`.

## Agents

Every agent's pilot result (cases `02_01`, `06_18`, `14_07`) is on the
[leaderboard](leaderboard.md). The runs behind it:

### Qwen 2.5 7B, all 35 cases (local)

Run through Ollama on a laptop GPU (RTX 4070, 8 GB), graded with Excel: 35 cases in 18
minutes, no API cost.

| Real models | Right numbers | Mean value correctness | Mean formula coverage | Mean traceability |
|---:|---:|---:|---:|---:|
| 0 / 35 | 0 / 35 | 2% | 50% | 30% |

The typical failures: target cells left empty, formulas that point at text labels instead
of numbers (so they return `#VALUE!` or text), and wrong row references. A small local
model sets a floor well below the coding agents.

### Free models through OpenRouter (pilot)

Chat mode: the model sees the workbook as text and replies with cell formulas; it cannot run
code. Graded with Excel on 25 September 2026.

| Model | `02_01` | `06_18` | `14_07` | Real models |
|---|---|---|---|---:|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | pass | pass | pass | 3 / 3 |
| `nvidia/nemotron-3-super-120b-a12b:free` | fail | pass | pass | 2 / 3 |
| `inclusionai/ling-3.0-flash-fin:free` | fail | pass | pass | 2 / 3 |
| `nex-agi/nex-n2.5-pro:free` | pass | pass | fail | 2 / 3 |
| `qwen/qwen3.8-27b:free` | pass | pass | pass | 3 / 3 |

Not on the leaderboard yet: `z-ai/glm-5.2:free` (1 pass, 1 fail, 1 case blocked by rate
limits) and `google/gemma-4-31b-it:free` (all 3 blocked). The free pool is shared and often
busy; re-running the same `--run-id` retries only the blocked cases. Qwen3.8 needed several
such passes, which is why its median time per case is 343 s.
`thinkingmachines/inkling:free` only serves coding-agent apps, so it cannot run in chat mode.

### Claude Opus 5.5, Sonnet 5 and Haiku 4.5 (pilot)

Each model ran as a Claude Code subagent with a fresh context: no conversation history and
no knowledge of Tickmark. The prompt was the same for every run: complete `TASK.md` in this
folder, use Python with openpyxl, save `output.xlsx`, and read nothing outside the folder.

| Setting | Value |
|---|---|
| Agent | Claude Code subagent, model set per run |
| Workbook editing | Python with openpyxl |
| Isolation | one temporary folder per case, outside the repository, with only `TASK.md` and `input.xlsx`; no web access |
| Engine | Excel |

| Model | `02_01` | `06_18` | `14_07` | Real models | Median time |
|---|---|---|---|---:|---:|
| Claude Opus 5.5 | pass | pass | pass | 3 / 3 | 80 s |
| Claude Sonnet 5 | pass | pass | pass | 3 / 3 | 146 s |
| Claude Haiku 4.5 | fail | pass | fail | 1 / 3 | 34 s |

The run transcripts show no file access outside each case folder. The workbooks were graded
as `manual` agents, like any workbook produced outside the runner. Haiku's formulas were
live but wrong in two places. On `02_01` it added growth rates that the workbook's own note
says compound, so the growth rates and the revenue forecast came out slightly low. On
`14_07` its loss-to-lease charged market rent on every unit, not only the occupied ones.
The loss came out about 3.5 times too large, and the unit count cancelled out of the total:
when the check changed the Studio count, `G20` did not move.

### OpenCode with GLM-5.2 (pilot)

| Setting | Value |
|---|---|
| CLI | OpenCode 1.18.18, paid OpenCode Zen account |
| Model | `opencode/glm-5.2` |
| Workbook editing | Python with openpyxl |
| Isolation | one temporary folder per case with only `TASK.md` and `input.xlsx`; no web access, subagents or files outside the folder |
| Engine | headless LibreOffice |

| Case | Duration | Value correctness | Formula coverage | Traceability | Outcome |
|---|---:|---:|---:|---:|---|
| `02_01` | 125 s | 100% | 100% | 100% | Pass |
| `06_18` | 56 s | 100% | 100% | 100% | Pass |
| `14_07` | 90 s | 100% | 100% | 100% | Pass |

Every input-change and perturbation check passed; no target was hardcoded. Agent output
is nondeterministic and three cases are a small sample, so this shows the harness works
end to end rather than estimating model quality. Compare runs only on the same cases,
model, timeout and engine.

## Known limitations

- **Untested branches.** The reference target formulas contain 91 decisions (`IF`,
  two-argument `MIN`/`MAX`, `IFERROR`, `ABS`). The input scenarios exercised 40 of them
  both ways; the rest are listed per case under `branch_coverage.untested`, typically a
  `MIN` whose arguments always scale together. A formula that differs only on such a
  branch can pass.
- **One domain, one source.** All cases come from SpreadsheetBench 2's Template category.
  The larger multi-sheet Financial_Model tasks are candidates for a harder tier.
- **Engines.** Grading needs Excel or LibreOffice; the `cached` engine skips the
  input-change and perturbation checks.

## Reproduce

```bash
# Reference self-test
uv run python scripts/run_benchmark.py --case data/cases --golden --engine excel --out results/verify/golden

# Broken workbooks: generate, grade, check against the manifests, compare graders
uv run python scripts/generate_malformed_outputs.py --case data/cases --output-root results/verify/malformed
uv run python scripts/run_benchmark.py --case data/cases --malformed-root results/verify/malformed --engine excel --out results/verify/malformed_reports
uv run python scripts/evaluate_malformed_results.py --malformed-root results/verify/malformed --reports-root results/verify/malformed_reports --engine excel --max-failures 0
uv run python scripts/compare_graders.py --reports-root results/verify/malformed_reports --engine excel

# OpenCode pilot (needs an OpenCode Zen login)
uv run python scripts/run_real_agent_suite.py --agents opencode --run-id opencode-pilot --engine libreoffice
```

Use `--engine libreoffice` on macOS or Linux. `run_benchmark.py` exits 1 on the broken
workbooks because every one of them fails, which is the expected result.
