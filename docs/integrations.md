# Integrations

Tickmark's agent runners also work on two external benchmarks, so the same agents can
be compared across task sets. Their data is downloaded locally and kept out of Git.

## BlueFin synthesis tasks

[BlueFin](https://github.com/Longitude-Labs/bluefin) is a finance spreadsheet-agent
benchmark with manipulation, synthesis and comprehension tasks, graded by an agentic
LLM judge against task rubrics. Tickmark integrates the **synthesis** task shape: task
folders with `input_workbook.xlsx`, `instruction.md`, `rubric.json`, `metadata.json`
and an optional `sample_output.xlsx`.

- Repository: <https://github.com/Longitude-Labs/bluefin>
- Data release: <https://huggingface.co/datasets/Longitude-Labs/bluefin-release>

Clone it under `data/bluefin/`:

```bash
git clone https://github.com/Longitude-Labs/bluefin data/bluefin
cd data/bluefin
uv sync
cd ../..
```

List the synthesis tasks:

```bash
uv run python scripts/run_bluefin.py --bluefin-root data/bluefin --list
```

Grade BlueFin's sample output for one task with BlueFin's own judge:

```bash
uv run python scripts/run_bluefin.py \
  --bluefin-root data/bluefin \
  --cases TTWO_Operating_Model_DCF \
  --sample \
  --judge-model gpt-5.4
```

Run configured agents on BlueFin tasks and grade their `output.xlsx` with the same
judge:

```bash
uv run python scripts/run_bluefin.py \
  --bluefin-root data/bluefin \
  --agents claude-code \
  --cases TTWO_Operating_Model_DCF \
  --run-id bluefin-pilot
```

For manual agents the script writes `TASK.md` and `input.xlsx` under
`results/bluefin/runs/<run-id>/<agent>/<case>/`; save the completed workbook there as
`output.xlsx` and run the same command again to grade it.

BlueFin grading is separate from Tickmark's deterministic audit. It shells out to
BlueFin's `scoring.grade`, prefers `data/bluefin/.venv/bin/python` when present, and
needs the judge model's API key in the environment (for example `OPENAI_API_KEY` for
`gpt-5.4`). Reports record BlueFin's `score_pct`, criterion counts and section scores;
the rollup treats `score_pct >= --pass-threshold` (default `0.8`) as a pass. Use
`--no-grade` to prepare or run agent workspaces without calling the judge.

## SheetCopilot examples

[SheetCopilot](https://github.com/BraveGroup/SheetCopilot) keeps task metadata in
`dataset.xlsx` / `dataset_20Samples.xlsx`, source workbooks in `task_sheets/`, and each
accepted answer as a final workbook plus a YAML checklist in `task_sheet_answers_v2/`.
Keep those files under `data/sheetcopilot/`. A first download set:

- `dataset/dataset.xlsx`
- `dataset/task_sheets/BoomerangSales.xlsx`
- `dataset/task_sheet_answers_v2/BoomerangSales/1_BoomerangSales/` (and `2_`, `3_`)

```bash
uv run python scripts/run_sheetcopilot.py \
  --dataset-workbook dataset.xlsx \
  --cases 3_BoomerangSales \
  --golden

uv run python scripts/run_sheetcopilot.py \
  --dataset-workbook dataset.xlsx \
  --cases 1_BoomerangSales \
  --workbook path/to/completed.xlsx
```

The local evaluator covers checklist fields openpyxl can read: cell values, basic
formatting, hyperlinks, filters, conditional-formatting signatures and frozen panes.
It reports chart and pivot-table checks as unsupported rather than approximating
SheetCopilot's LibreOffice/UNO evaluator; use the upstream evaluator for those.

With all nine BoomerangSales tasks downloaded, the reference self-test passes tasks 3,
4 and 5. Tasks 1, 2 and 6-9 include chart or pivot-table checks, so they fail as
unsupported even though their cell-value checks pass. These tasks do not overlap with
the financial-model cases, so the comparison on Tickmark's own cases uses SheetCopilot's
cell-value rule ([grader comparison](methodology.md#grader-comparison)).
