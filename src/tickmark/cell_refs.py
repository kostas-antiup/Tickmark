"""Cell-address helpers and formula reference extraction.

Cells are identified by canonical sheet-qualified keys such as ``RentRoll!C17``:
unquoted sheet name, ``!``, then the column/row address without ``$``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries

_CELL = re.compile(r"^\$?[A-Z]{1,3}\$?\d+$")
_AREA = re.compile(r"^\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+$")
_COLUMNS = re.compile(r"^\$?[A-Z]{1,3}:\$?[A-Z]{1,3}$")
_ROWS = re.compile(r"^\$?\d+:\$?\d+$")

SheetBounds = Mapping[str, tuple[int, int]]
DefinedNames = Mapping[str, Sequence[tuple[str, str]]]


def cell_key(sheet: str, address: str) -> str:
    """Return the canonical key for one cell, e.g. ``cell_key("RentRoll", "$C$17")``."""

    return f"{sheet}!{address.replace('$', '').upper()}"


def split_reference(reference: str, default_sheet: str | None = None) -> tuple[str, str]:
    """Split ``'My Sheet'!A1:B2`` into ``("My Sheet", "A1:B2")``."""

    if "!" not in reference:
        if default_sheet is None:
            raise ValueError(f"reference {reference!r} has no sheet name")
        return default_sheet, reference
    sheet, area = reference.rsplit("!", 1)
    if len(sheet) >= 2 and sheet[0] == sheet[-1] == "'":
        sheet = sheet[1:-1].replace("''", "'")
    return sheet, area


def expand_area(sheet: str, area: str, bounds: tuple[int, int] | None = None) -> list[str]:
    """Expand ``A1``, ``A1:B2``, ``A:A`` or ``1:1`` into cell keys (row-major order).

    Whole-column and whole-row areas need ``bounds`` = (max_row, max_column).
    """

    clean = area.replace("$", "").upper()
    min_col, min_row, max_col, max_row = range_boundaries(clean)
    if max_row is None or max_col is None:
        if bounds is None:
            raise ValueError(f"area {area!r} needs sheet bounds to expand")
        max_row = max_row or bounds[0]
        max_col = max_col or bounds[1]
    min_col, min_row = min_col or 1, min_row or 1
    return [
        cell_key(sheet, f"{get_column_letter(column)}{row}")
        for row in range(min_row, max_row + 1)
        for column in range(min_col, max_col + 1)
    ]


def expand_reference(reference: str) -> list[str]:
    """Expand a case-metadata reference such as ``RentRoll!C17:G20`` into cell keys."""

    sheet, area = split_reference(reference)
    return expand_area(sheet, area)


@dataclass(frozen=True)
class FormulaReferences:
    """Cells a formula depends on, split by how they are referenced."""

    direct: frozenset[str] = frozenset()
    ranged: frozenset[str] = frozenset()
    unresolved: tuple[str, ...] = ()
    literals: tuple[float, ...] = ()


def parse_formula(
    formula: str,
    sheet: str,
    *,
    sheet_bounds: SheetBounds | None = None,
    defined_names: DefinedNames | None = None,
) -> FormulaReferences:
    """Extract cell references and numeric literals from one formula.

    Single-cell references are ``direct``; cells inside an area (``C17:C19``,
    ``A:A``) are ``ranged``. External-workbook links, 3-D references, unknown
    sheets and unknown names are returned as ``unresolved`` token text.
    """

    bounds = sheet_bounds or {}
    names = defined_names or {}
    direct: set[str] = set()
    ranged: set[str] = set()
    unresolved: list[str] = []
    literals: list[float] = []
    try:
        tokens = Tokenizer(formula).items
    except Exception:
        return FormulaReferences(unresolved=(formula,))

    for token in tokens:
        if token.type != "OPERAND":
            continue
        if token.subtype == "NUMBER":
            try:
                literals.append(float(token.value))
            except ValueError:
                pass
            continue
        if token.subtype != "RANGE":
            continue
        text = token.value
        if "[" in text:
            unresolved.append(text)
            continue
        if "!" in text:
            ref_sheet, area = split_reference(text)
        elif text.upper() in names:
            for name_sheet, name_area in names[text.upper()]:
                _add_area(name_sheet, name_area, bounds, direct, ranged, unresolved)
            continue
        else:
            ref_sheet, area = sheet, text
        _add_area(ref_sheet, area, bounds, direct, ranged, unresolved, original=text)

    return FormulaReferences(
        direct=frozenset(direct),
        ranged=frozenset(ranged - direct),
        unresolved=tuple(unresolved),
        literals=tuple(literals),
    )


def _add_area(
    sheet: str,
    area: str,
    bounds: SheetBounds,
    direct: set[str],
    ranged: set[str],
    unresolved: list[str],
    original: str | None = None,
) -> None:
    clean = area.replace("$", "").upper()
    known_sheet = not bounds or sheet in bounds
    if known_sheet and _CELL.match(clean):
        direct.add(cell_key(sheet, clean))
    elif known_sheet and _AREA.match(clean):
        ranged.update(expand_area(sheet, clean))
    elif sheet in bounds and (_COLUMNS.match(clean) or _ROWS.match(clean)):
        ranged.update(expand_area(sheet, clean, bounds[sheet]))
    else:
        unresolved.append(original or f"{sheet}!{area}")
