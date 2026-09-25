# Security

Tickmark runs other people's code and opens other people's files. Keep that in mind before
you run an agent or grade a workbook you do not trust.

## Agents

`cli` agents are third-party programs. Each one runs in a temporary folder outside the
repository that holds only `TASK.md` and `input.xlsx`, and the configured Claude Code and
OpenCode commands limit the agent to file edits and Python. The agent still runs with your
user rights and your network access, so a misbehaving agent could read or change other
files. Run agents you do not trust in a container or a virtual machine.

`chat` agents receive the workbook as text. Their replies are written into a copy of
`input.xlsx` as cell values and formulas, which are then recalculated like any other
submission.

## Workbooks

Grading recalculates each workbook in Microsoft Excel or LibreOffice. Excel opens a
read-only temporary copy with link updates, alerts and events turned off. LibreOffice runs
headless with a throwaway profile. Formulas can still call functions that reach the network,
such as `WEBSERVICE`, so grade workbooks from unknown sources on a machine you are willing
to expose, or in a virtual machine.

## Reporting a vulnerability

Please report security problems privately: open the repository's **Security** tab and choose
**Report a vulnerability**. Do not open a public issue for them.
