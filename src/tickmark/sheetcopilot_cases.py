"""Load SheetCopilot benchmark cases from an upstream dataset checkout.

SheetCopilot keeps the task metadata, source workbook and reference answers in
separate folders. This module turns that layout into case objects without
copying the upstream files into ``data/cases``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl


@dataclass(frozen=True)
class SheetCopilotReference:
    """One acceptable final workbook and its checklist."""

    workbook: Path
    checklist: Path
    check_board: Mapping[str, Mapping[str, Mapping[str, bool]]]
    required_apis: tuple[str, ...]

    @property
    def reference_id(self) -> str:
        return self.workbook.stem


@dataclass(frozen=True)
class SheetCopilotCase:
    """One SheetCopilot task with its source workbook and reference answers."""

    case_id: str
    sheet_name: str
    task_no: int
    context: str
    instruction: str
    input_workbook: Path
    reference_dir: Path
    references: tuple[SheetCopilotReference, ...]
    categories: tuple[str, ...] = ()
    atomic_actions: tuple[str, ...] = ()
    source_dataset: Path | None = None


def load_sheetcopilot_cases(
    dataset_root: Path | str,
    *,
    dataset_workbook: str = "dataset_20Samples.xlsx",
    answer_dir: str = "task_sheet_answers_v2",
    case_ids: Iterable[str] | None = None,
) -> list[SheetCopilotCase]:
    """Load cases listed in ``dataset_workbook`` from a SheetCopilot checkout.

    The expected upstream layout is::

        dataset_root/
          dataset_20Samples.xlsx
          task_sheets/<Sheet Name>.xlsx
          task_sheet_answers_v2/<Sheet Name>/<No.>_<Sheet Name>/

    ``case_ids`` uses the same ``<No.>_<Sheet Name>`` naming convention as the
    SheetCopilot result folders.
    """

    root = Path(dataset_root)
    selected = set(case_ids or ())
    dataset_path = root / dataset_workbook
    rows = _dataset_rows(dataset_path)
    cases: list[SheetCopilotCase] = []
    for row in rows:
        sheet_name = str(row["sheet_name"]).strip()
        task_no = int(row["no"])
        case_id = f"{task_no}_{sheet_name}"
        if selected and case_id not in selected:
            continue
        reference_dir = root / answer_dir / sheet_name / case_id
        cases.append(
            SheetCopilotCase(
                case_id=case_id,
                sheet_name=sheet_name,
                task_no=task_no,
                context=str(row.get("context") or "").strip(),
                instruction=str(row.get("instructions") or "").strip(),
                input_workbook=root / "task_sheets" / f"{sheet_name}.xlsx",
                reference_dir=reference_dir,
                references=load_sheetcopilot_references(reference_dir),
                categories=_split_list(row.get("categories")),
                atomic_actions=_split_list(row.get("atomic_actions")),
                source_dataset=dataset_path,
            )
        )
    return cases


def load_sheetcopilot_references(reference_dir: Path | str) -> tuple[SheetCopilotReference, ...]:
    """Load every ``*_gtN.xlsx`` + ``*_gtN_check.yaml`` pair in a reference folder."""

    directory = Path(reference_dir)
    references: list[SheetCopilotReference] = []
    for workbook in sorted(directory.glob("*_gt*.xlsx")):
        checklist = workbook.with_name(f"{workbook.stem}_check.yaml")
        if not checklist.exists():
            continue
        parsed = _parse_sheetcopilot_yaml(checklist.read_text(encoding="utf-8"))
        check_board = parsed.get("check_board")
        if not isinstance(check_board, dict):
            raise ValueError(f"{checklist} does not define a check_board mapping")
        required = parsed.get("required_APIs", ())
        references.append(
            SheetCopilotReference(
                workbook=workbook,
                checklist=checklist,
                check_board=_bool_board(check_board),
                required_apis=tuple(str(item) for item in required),
            )
        )
    return tuple(references)


def sheetcopilot_prompt(case: SheetCopilotCase) -> str:
    """Prompt text comparable to what a SheetCopilot task row provides."""

    if case.context:
        return f"Context: {case.context}\n\nTask: {case.instruction}"
    return case.instruction


def _dataset_rows(path: Path) -> list[dict[str, Any]]:
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = book.active
    rows = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration as error:
        raise ValueError(f"{path} is empty") from error
    headers = {_normalize_header(value): index for index, value in enumerate(header_row)}
    required = {
        "sheet_name": "sheetname",
        "no": "no",
        "context": "context",
        "instructions": "instructions",
        "categories": "categories",
        "atomic_actions": "atomicactions",
    }
    missing = [label for label, normalized in required.items() if normalized not in headers]
    if missing:
        raise ValueError(f"{path} is missing SheetCopilot column(s): {', '.join(missing)}")

    loaded: list[dict[str, Any]] = []
    for values in rows:
        if all(value in (None, "") for value in values):
            continue
        row = {
            label: values[headers[normalized]]
            for label, normalized in required.items()
            if headers[normalized] < len(values)
        }
        if row.get("sheet_name") in (None, "") or row.get("no") in (None, ""):
            continue
        loaded.append(row)
    return loaded


def _normalize_header(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _split_list(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    text = str(value).replace("\n", ",").replace(";", ",")
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _bool_board(data: Mapping[Any, Any]) -> dict[str, dict[str, dict[str, bool]]]:
    board: dict[str, dict[str, dict[str, bool]]] = {}
    for sheet_index, aspects in data.items():
        if not isinstance(aspects, dict):
            continue
        board[str(sheet_index)] = {}
        for aspect, fields in aspects.items():
            if not isinstance(fields, dict):
                continue
            board[str(sheet_index)][str(aspect)] = {
                str(field): bool(enabled) for field, enabled in fields.items()
            }
    return board


def _parse_sheetcopilot_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by SheetCopilot checklists.

    The upstream files are nested mappings of strings to booleans plus simple
    string lists. Keeping this parser local avoids adding a general YAML runtime
    dependency for benchmark metadata.
    """

    lines = [
        (len(raw) - len(raw.lstrip(" ")), raw.strip())
        for raw in text.splitlines()
        if raw.strip() and not raw.lstrip().startswith("#")
    ]
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, root)]
    for index, (indent, content) in enumerate(lines):
        if content.startswith("- "):
            while indent < stack[-1][0] or (
                indent == stack[-1][0] and not isinstance(stack[-1][1], list)
            ):
                stack.pop()
            parent = stack[-1][1]
            if not isinstance(parent, list):
                raise ValueError(f"list item without list parent: {content}")
            parent.append(_yaml_scalar(content[2:]))
            continue
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        key, separator, raw_value = content.partition(":")
        if not separator:
            raise ValueError(f"unsupported YAML line: {content}")
        key = _yaml_key(key)
        value = raw_value.strip()
        if value:
            if not isinstance(parent, dict):
                raise ValueError(f"mapping entry inside list: {content}")
            parent[key] = _yaml_scalar(value)
            continue
        child: dict[str, Any] | list[Any]
        child = [] if _next_is_list(lines, index, indent) else {}
        if not isinstance(parent, dict):
            raise ValueError(f"nested mapping inside list: {content}")
        parent[key] = child
        stack.append((indent, child))
    return root


def _next_is_list(lines: list[tuple[int, str]], index: int, indent: int) -> bool:
    for next_indent, next_content in lines[index + 1 :]:
        if next_indent < indent:
            return False
        return next_content.startswith("- ")
    return False


def _yaml_key(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _yaml_scalar(value: str) -> Any:
    text = _yaml_key(value)
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None
    return text
