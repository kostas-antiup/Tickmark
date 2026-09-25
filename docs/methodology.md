# Methodology

Tickmark grades the workbook an agent delivers, not only the numbers it shows. A
target cell that holds the right constant is a construction failure; so is a formula
that looks live but carries a pasted number, or logic that only fits the original
inputs.

## Protocol

1. **Isolate the agent.** It receives the case instruction and `input.xlsx`, a copy of
   the reference workbook with the target cells blank. `golden.xlsx` and `case.json`
   never enter its workspace.
2. **Preserve the submission.** The delivered `output.xlsx` is graded from a copy.
3. **Recalculate.** Workbooks written by libraries such as openpyxl carry no computed
   values, so every submission is recalculated in a real spreadsheet engine before
   anything is compared (see [Engines](#engines)).
4. **Audit.** Seven checks run against the hidden reference model.
5. **Report each axis separately.** Value correctness, formula coverage and
   traceability are reported as scores; the verdict follows the rules below.

## Checks

| Check | Fails when |
|---|---|
| `value_correctness` | a target value differs from the reference (absolute and relative tolerance from `case.json`, `1e-6` by default) |
| `formula_coverage` | a target cell holds a constant or is empty |
| `traceability` | a target's formula chain does not end at declared input cells on every path |
| `no_unexpected_hardcoded_values` | a hardcoded number sits inside a target's formula chain |
| `no_fake_formulas` | a formula references no cells, for example `=9080487` |
| `input_change_check` | after the case's input cell changes, the final output does not move to the reference's recalculated value |
| `perturbation_check` | in any input scenario, a target no longer matches the reference recalculated with the same inputs |

For target cells `T`:

- `value_correctness = correct_values / |T|`
- `formula_coverage = targets_with_formulas / |T|`
- `traceability = targets_reaching_declared_inputs / |T|`

A workbook is **correct** when every value matches, **auditable** when every
construction check passes (skipped checks do not count), and **passes** when it is
both. Formulas are never compared as text: `SUM(C20:F20)` and `C20+D20+E20+F20` are
equally right if they behave the same under the checks.

## Input scenarios

The perturbation check recalculates the submission and the reference under the same
changed inputs ([`scenarios.py`](../src/tickmark/scenarios.py)).

**Fixed scenarios**, always run:

| Scenario | Change |
|---|---|
| `up` | every other numeric input +5% to +25% |
| `down` | every other numeric input -5% to -25% |
| `mixed` | each input up or down by its own amount |
| `switches` | every 0/1 input flipped (only when the case has them) |
| `years` | every year-like input (1900-2100) +1 (only when the case has them) |

Amounts are deterministic, so reruns are comparable.

**Branch-seeking scenarios.** Two formulas can agree on every fixed scenario and still
differ on an `IF` branch none of them reaches. Tickmark finds every decision in the
reference's target formulas (`IF`, two-argument `MIN`/`MAX`, `IFERROR`, `ABS`) and
tries wider changes to flip each one: 16 random scenarios (inputs x0.4 to x1.9,
switches flipped at random), then, for decisions still seen one way only, each input
they depend on alone at x4 and x0.25. A scenario is kept only if it flips a decision
not yet seen both ways, up to 10 kept scenarios.

Scenarios and reference results are computed once per case and engine.
`branch_coverage` in each report shows how many reference decisions were tested both
ways and lists the rest under `untested`. Those remain blind spots, for example a `MIN`
whose arguments always scale together.

## Per-input diagnosis

With `--sensitivity`, a workbook that fails the perturbation check is recalculated once
more per input, changing that input alone (switches flipped, years +1, anything else
+15%). The report then names the inputs a wrong cell ignores. For case `14_07` with
`G20 = C20+D20+E20+1161600`:

> RentRoll!G20 diverges from the reference when RentRoll!F7, RentRoll!F10, RentRoll!F12,
> RentRoll!F14 or RentRoll!F16 changes alone.

Targets that diverge only when several inputs change together are reported as such
(typically a different `IF`/`MIN`/`MAX` branch). It costs one extra recalculation per
input, so it is off by default.

## Warnings

`warnings` in a report are for review and never change the verdict:

- **Input footprint**: a target formula depends on different input cells than the
  reference, named at the root cell only (for example "G20 does not use F7, F10, F12,
  F14, F16"). The structured list is in `input_differences`.
- **Embedded constants**: numeric literals in target formulas that the reference does
  not use (for example `1.2` in `=C7*C10*1.2*10`). Ordinary unit conversions such as
  12 months or 365 days are ignored.

## Engines

`--engine` selects how workbooks are recalculated. `auto` (default) uses the first
available of `excel`, `libreoffice`, `cached`.

| Engine | How | Notes |
|---|---|---|
| `excel` | Microsoft Excel via COM on a temporary copy | Windows with Excel; `pywin32` comes with the `audit` extra. Excel is restarted and the call retried once if COM drops mid-run. |
| `libreoffice` | Headless LibreOffice on temporary copies | Any OS with `soffice`. Input values are patched straight into the sheet XML and results read back from it; larger batches run in up to 4 processes (`TICKMARK_LIBREOFFICE_WORKERS` overrides). Reproduces Excel's values on all 35 cases. |
| `cached` | Values last saved in the file | Cannot change inputs, so the input-change and perturbation checks are skipped. Not reliable for value correctness on files written by openpyxl. |

## Grader comparison

Every report also records how value-only benchmarks would grade the same recalculated
workbook ([`baselines.py`](../src/tickmark/baselines.py)), so a run shows where Tickmark
is stricter or more lenient on identical files.

| Grader | Rule, reproduced from the upstream code |
|---|---|
| `spreadsheetbench` | SpreadsheetBench's `evaluation.py`: every cell of the task's original `answer_position` equals the reference after rounding numbers to 2 decimals; blank equals empty text; different types differ. |
| `sheetcopilot` | SheetCopilot's `cells.values` checklist rule: every cell of each task sheet's used range equals the reference within `1e-8`. |

Both read the recalculated values, and cells with volatile formulas such as `TODAY()`
are left out, since they can never match a saved reference. The reverse disagreement
also happens: helper values written inside the reference's used range fail those
graders even when the model itself is correct.

## Exit codes

`scripts/run_benchmark.py` exits `0` when every workbook passes, `1` when any fails its
checks, `2` on bad arguments and `3` when a workbook could not be graded at all. Such a
workbook gets a report with `"passed": null` and the error, and the run continues.
