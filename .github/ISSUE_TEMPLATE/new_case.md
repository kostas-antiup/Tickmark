---
name: New case
about: Propose a financial model for the benchmark
labels: new case
---

**Source**

Where the task and its reference workbook come from, and their license.

**The model**

What it computes, which cells the agent must fill, and the final output cell.

**Checklist** ([data/cases/README.md](https://github.com/kostas-antiup/Tickmark/blob/main/data/cases/README.md) explains each rule)

- [ ] `input.xlsx` equals `golden.xlsx` except for blank target cells
- [ ] every target in the golden is a live formula that traces back to numeric input cells
- [ ] no volatile or iterative function sits in a chain
- [ ] every assumption is an input cell or stated on the sheet
- [ ] the final output changes when an input changes
- [ ] the golden passes its own case, and every generated broken variant fails
