# Benchmark cases

35 financial-model cases selected from SpreadsheetBench 2 (`Template` category):
32 tier-A cases (same profile as `14_07`) and 3 tier-B cases (tier A plus a few cells the
golden fixes at 0). `selection_report.json` records why each of the 97 Template tasks was selected
or excluded, and why the Visualization, Debugging and Financial_Model categories were left out.

## Layout

```
data/cases/
  index.json              # manifest: one row per case
  selection_report.json   # criteria + per-task decisions for all 97 Template tasks
  <id>/
    input.xlsx            # VISIBLE to the agent (targets are blank)
    golden.xlsx           # HIDDEN: reference workbook with formulas + cached values
    case.json             # HIDDEN: metadata used by the runner/evaluator
```

**Visibility rule:** the agent receives only `input.xlsx` and `case.json["instruction"]`. Never
copy `golden.xlsx` or `case.json` into the agent's workspace; they contain the answers.

Workbooks are byte-identical copies of the SpreadsheetBench 2 files (`source_paths` in each
`case.json`).

## case.json fields

| Field | Meaning |
|---|---|
| `instruction` | Prompt given to the agent: the original instruction + the target ranges + "use live formulas, do not hardcode". |
| `source_instruction` | Original SpreadsheetBench instruction, verbatim. |
| `target_cells` | Cells the agent must fill (blank in input, formulas in golden). Graded for value, formula coverage and traceability. |
| `final_output` | Main output cell: the target that depends on the most other targets and has a non-zero value. |
| `key_outputs` | `final_output` plus other terminal outputs, together covering 79%-100% of targets. |
| `expected_outputs` | Golden values for `key_outputs`. Values for all targets: read `golden.xlsx` with `data_only=True`. |
| `input_cells` | All numeric constants in `input.xlsx` (every legitimate endpoint of a formula chain). |
| `golden_input_cells` | The subset of `input_cells` the golden formulas actually use. |
| `allowed_hardcoded_cells` | Tier B only: cells the golden fixes at 0. Excluded from `target_cells`; treat them as valid chain endpoints, like inputs. |
| `input_change_check` | A verified dynamic test: +10% on `cell` changes `final_output` from `output_before` to `output_after_in_golden`. |
| `value_tolerance` | Suggested tolerance (`abs` 1e-6, `rel` 1e-6). |
| `verification` | Excel recalculation result of the golden (all targets matched cached values). |
| `stats`, `notes` | Size, functions used, multi-sheet flag, array-formula count, case-specific quirks. |

## How the cases were selected

A case is kept only if:
- its input equals its golden except for blank target cells;
- every golden target is a live formula;
- every target traces through formulas to numeric input constants (no cycles, no references to
  empty cells, no `IRR`/volatile functions in the chain);
- every assumption the golden uses is either an input cell or stated on the sheet;
- its final output is non-zero and responds to an input change.

Every selected golden was recalculated in Microsoft Excel. All target values matched the cached
values, and the `input_change_check` was run against the golden itself.

## Evaluator gotchas

- **Array formulas.** 18 cases store some target formulas as array formulas. openpyxl returns an
  `ArrayFormula` object for these, not a string: use `cell.value.text` to get `=...`.
- **No cached values in agent output.** If the agent writes formulas with openpyxl, the saved file
  has no computed values. Recalculate it (Excel COM or headless LibreOffice) before reading values
  with `data_only=True`.
- **Absolute and cross-sheet references.** Strip `$` when parsing (`$C$13`). Cases marked
  multi-sheet (e.g. `14_06` uses `SharedData!C5`) need sheet-qualified addresses.
- **Embedded literals.** Some golden formulas legitimately contain constants stated on the sheet
  (`*12` months, `/90` days per quarter, `*0.03` for "3% of EGR"). A "no hardcoded numbers in
  formulas" rule would flag these, so check against `notes` before adding one.

## Cases

| id | tier | family | targets | final output | label | expected | multi-sheet | array targets |
|---|---|---|---|---|---|---|---|---|
| `02_01` | A | 02_cash_sweep | 27 | `Revenue_Analysis!F29` | Projected Revenue / Year 4 | 4,976 |  | 4 |
| `02_03` | A | 02_cash_sweep | 49 | `DebtWaterfall!F25` | Ending Balance / Q4 | 1,420 |  |  |
| `02_05` | A | 02_cash_sweep | 72 | `DebtWaterfall!E34` | Total interest expense / Year 4 | 16.2 |  | 16 |
| `02_06` | A | 02_cash_sweep | 64 | `DebtWaterfall!E31` | Interest expense / Year 4 | 68 |  | 12 |
| `04_04` | A | 04_dcf_valuation | 36 | `FCF_Calc!G28` | Free Cash Flow / Q4 2025 | 33.8276 |  | 4 |
| `06_02` | A | 06_equity_forecast | 44 | `WC_Forecast!H32` | Total Change in Working Capital / Q2 2025E | -68.274 |  |  |
| `06_03` | A | 06_equity_forecast | 127 | `iPhone_Revenue_Build!J46` | Total Revenue YoY Growth % / Q4'24 | 0.4425 |  |  |
| `06_04` | A | 06_equity_forecast | 26 | `DrugRevenue!J17` | Total Vexira Revenue / FY2027 | 10,064 | yes |  |
| `06_05` | A | 06_equity_forecast | 24 | `WorkingCapital!F27` | Change in Net Working Capital / 4Q25 | -39.3577 |  |  |
| `06_12` | A | 06_equity_forecast | 30 | `CashFlow_Build!M14` | Cash from Operations / 2025E | 203 |  |  |
| `06_13` | A | 06_equity_forecast | 127 | `CashFlowBuild!J51` | Ending cash balance / Q4 2025 | 427.5 |  | 39 |
| `06_15` | A | 06_equity_forecast | 41 | `WorkingCapital!D24` | Change in Working Capital / Q2 2023 | 95.2222 |  |  |
| `06_18` | A | 06_equity_forecast | 20 | `WorkingCapital_Forecast!E21` | Change in Net Working Capital / Q2 FY24E | 211.3778 |  |  |
| `06_21` | A | 06_equity_forecast | 27 | `WorkingCapital!F32` | Cash Flow Impact (use of cash) / 2025E | 98.6712 |  |  |
| `06_24` | A | 06_equity_forecast | 39 | `RevenueBuild!G32` | Total Revenue / FY 2023 | 3,104 |  | 6 |
| `08_01` | A | 08_fin_model_basics | 40 | `DebtSchedule!G13` | Total Interest Expense / Year 5 | -68.3774 |  |  |
| `09_03` | A | 09_lbo_model | 73 | `Sheet!H30` | Average Balance / Year 5 | 45 |  | 18 |
| `09_04` | A | 09_lbo_model | 97 | `DebtSchedule!M25` | Ending Balance / Year 5 | 38.5 |  | 42 |
| `10_01` | A | 10_ma_analysis | 25 | `EPS_Accretion!C50` | Accretion/(Dilution) % / Year 1 | -0.1042 |  | 6 |
| `10_02` | A | 10_ma_analysis | 27 | `EPS_Accretion!C40` | Accretion / (Dilution) % / FY1 | 0.1693 |  |  |
| `11_01` | A | 11_ma_model | 49 | `DebtSchedule!K15` | Interest expense / Year 7 | 13.0868 |  | 15 |
| `11_02` | A | 11_ma_model | 48 | `PPA!H33` | Change / Year 5 | -9.38 |  | 14 |
| `11_04` | A | 11_ma_model | 28 | `PPA!H35` | Ending Balance / Q2 Year 2 | 105.56 |  |  |
| `14_02` | A | 14_re_dcf | 83 | `OpEx_Projection!L27` | TOTAL OPERATING EXPENSES / Year 5 | 1,754,403 |  |  |
| `14_03` | A | 14_re_dcf | 55 | `NOI_Projection!C49` | Net Sale Proceeds / Year 2 | 67,371,399 |  | 1 |
| `14_04` | A | 14_re_dcf | 71 | `OpEx_Projection!G47` | TOTAL OPERATING EXPENSES / Year 5 | 2,186,214 |  | 1 |
| `14_05` | A | 14_re_dcf | 65 | `NOI_Projection!O39` | Year 5 / Net Operating Income | 3,127,866 |  | 7 |
| `14_06` | A | 14_re_dcf | 42 | `OpEx_Projection!I34` | TOTAL / Total OpEx | 25,092,705 | yes | 2 |
| `14_07` | A | 14_re_dcf | 20 | `RentRoll!G20` | Net Rental Revenue / TOTAL | 9,080,487 |  |  |
| `14_08` | A | 14_re_dcf | 141 | `OpEx_Projection!G47` | Net Operating Income / Year 1 Total | 5,061,975 |  | 10 |
| `16_01` | A | 16_re_direct_cap | 35 | `DirectCap!D46` | Property Valuation / Annual Total | 176,060,983 |  |  |
| `16_04` | A | 16_re_direct_cap | 28 | `RentRoll!O13` | TOTALS / Net Rental Revenue (Annual) | 12,150,480 |  |  |
| `06_23` | B | 06_equity_forecast | 52 | `WorkingCapital!E52` | Cash Flow from Operating Activities / 2023A | 1,580 |  | 5 |
| `13_06` | B | 13_nonrecurring | 73 | `FinancialNormalization!I36` | Normalized Diluted EPS / 2025E | 0.7533 |  |  |
| `14_09` | B | 14_re_dcf | 69 | `Revenue_Projection!I46` | Sum / Total | 37,207,665 |  | 5 |

## Normalized instructions

`instruction` extends the original SpreadsheetBench wording with the target ranges and the
rule to use live formulas. Case `14_07` also states business context the source leaves out:
the schedule reports annual amounts, rows 10 and 12 are monthly per-unit rent inputs, and
row 16 is the vacant-unit input despite its incorrect label. This makes the task determinate
without revealing the reference formulas or values. `source_instruction` keeps the original
text for provenance.

## Source and license

The workbooks come from [SpreadsheetBench 2](https://github.com/RUCKBReasoning/SpreadsheetBench-2)
(dataset: [KAKA22/SpreadsheetBench-v2](https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2)),
released under the MIT License. They are redistributed unmodified; credit belongs to the
SpreadsheetBench 2 authors. The case metadata (`case.json`, `index.json`,
`selection_report.json`) is part of Tickmark and covered by this repository's MIT License.
