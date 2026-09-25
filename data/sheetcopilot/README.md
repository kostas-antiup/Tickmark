# SheetCopilot examples

This folder is for local SheetCopilot files downloaded from
<https://github.com/BraveGroup/SheetCopilot>. The downloaded workbooks are not
committed.

Expected layout:

```text
data/sheetcopilot/
  dataset_20Samples.xlsx          # or dataset.xlsx, selected with --dataset-workbook
  task_sheets/
    BoomerangSales.xlsx
  task_sheet_answers_v2/
    BoomerangSales/
      1_BoomerangSales/
        1_BoomerangSales_gt1.xlsx
        1_BoomerangSales_gt1_check.yaml
```

Start with the BoomerangSales cases because the upstream repo exposes them as a
compact contiguous example family:

- `dataset/dataset.xlsx`
- `dataset/task_sheets/BoomerangSales.xlsx`
- `dataset/task_sheet_answers_v2/BoomerangSales/1_BoomerangSales/`
- `dataset/task_sheet_answers_v2/BoomerangSales/2_BoomerangSales/`
- `dataset/task_sheet_answers_v2/BoomerangSales/3_BoomerangSales/`

Run a reference self-test after downloading:

```bash
uv run python scripts/run_sheetcopilot.py \
  --dataset-workbook dataset.xlsx \
  --cases 3_BoomerangSales \
  --golden
```

The in-repo evaluator intentionally supports the openpyxl-readable checklist
subset: cell values, basic cell formatting, hyperlinks, filters, conditional
formatting signatures and frozen panes. Chart and pivot-table checklist fields
are reported as unsupported; use SheetCopilot's upstream Ubuntu evaluator for
`1_BoomerangSales`, `2_BoomerangSales`, or any other task where those fields are
the target metric.
