"""Fast paths for the LibreOffice engine: patch input values and read saved values as XML.

An openpyxl round trip parses and re-serialises the whole workbook (styles included),
which costs more than the recalculation itself when a case needs dozens of scenario
copies. These helpers touch only the parts that matter and hand anything unusual
back to openpyxl: ``XlsxTemplate.write`` returns False and ``read_saved_values``
raises, and the caller then takes the openpyxl route.
"""

from __future__ import annotations

import datetime
import posixpath
import re
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format, is_timedelta_format
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

from .cell_refs import split_reference

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


def sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map each sheet name to its XML part, e.g. ``{"RentRoll": "xl/worksheets/sheet1.xml"}``."""

    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target", "") for rel in rels.iter(_PACKAGE_REL)}
    parts = {}
    for sheet in workbook.iter(f"{_MAIN}sheet"):
        target = targets.get(sheet.get(_REL_ID), "")
        parts[sheet.get("name", "")] = (
            target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
        )
    return parts


class XlsxTemplate:
    """A workbook read once, written out many times with different input constants."""

    def __init__(self, source: Path) -> None:
        with zipfile.ZipFile(source) as archive:
            self._infos = archive.infolist()
            self._parts = {info.filename: archive.read(info) for info in self._infos}
            self._sheets = sheet_parts(archive)

    def write(self, target: Path, changes: Mapping[str, Any]) -> bool:
        """Write a copy with ``changes`` applied; False (nothing written) if one needs openpyxl.

        Only numeric or boolean values over existing constant cells are patched;
        formula cells (possibly shared), missing cells and text go through openpyxl.
        Changes on sheets the workbook does not have are ignored.
        """

        patched = dict(self._parts)
        by_part: dict[str, dict[str, Any]] = {}
        for key, value in changes.items():
            sheet, address = split_reference(key)
            part = self._sheets.get(sheet)
            if part is None:
                continue
            if part not in patched or not isinstance(value, (bool, int, float)):
                return False
            by_part.setdefault(part, {})[address.replace("$", "").upper()] = value
        for part, cells in by_part.items():
            try:
                text = patched[part].decode("utf-8")
            except UnicodeDecodeError:
                return False
            for address, value in cells.items():
                text = _patch_cell(text, address, value)
                if text is None:
                    return False
            patched[part] = text.encode("utf-8")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for info in self._infos:
                archive.writestr(info, patched[info.filename])
        return True


def _patch_cell(text: str, address: str, value: Any) -> str | None:
    match = re.search(rf'<c(\s+r="{address}"[^>]*?)(?:/>|>(.*?)</c>)', text, re.DOTALL)
    if match is None or "<f" in (match.group(2) or ""):
        return None
    style = re.search(r'\ss="\d+"', match.group(1))
    attributes = f'r="{address}"{style.group(0) if style else ""}'
    if isinstance(value, bool):
        cell = f'<c {attributes} t="b"><v>{int(value)}</v></c>'
    else:
        cell = f"<c {attributes}><v>{value!r}</v></c>"
    return text[: match.start()] + cell + text[match.end() :]


def read_saved_values(workbook: Path, cells: Iterable[str]) -> dict[str, Any]:
    """Saved values of ``cells``, as openpyxl's ``load_workbook(data_only=True)`` returns them."""

    wanted: dict[str, dict[str, str]] = {}
    for key in cells:
        sheet, address = split_reference(key)
        wanted.setdefault(sheet, {})[address.replace("$", "").upper()] = key
    values: dict[str, Any] = {
        key: None for addresses in wanted.values() for key in addresses.values()
    }
    with zipfile.ZipFile(workbook) as archive:
        names = set(archive.namelist())
        sheets = sheet_parts(archive)
        strings = _shared_strings(archive) if "xl/sharedStrings.xml" in names else []
        dates, durations, epoch = _date_styles(archive, names)
        for sheet, addresses in wanted.items():
            part = sheets.get(sheet)
            if part is None or part not in names:
                continue
            with archive.open(part) as stream:
                for _, element in ElementTree.iterparse(stream):
                    if element.tag != f"{_MAIN}c":
                        continue
                    key = addresses.get(element.get("r", ""))
                    if key is not None:
                        values[key] = _cell_value(element, strings, dates, durations, epoch)
                    element.clear()
    return values


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.iter(f"{_MAIN}si"):
        # Plain text sits in <t>; rich text in <r><t>; phonetic hints (<rPh>) are skipped.
        runs = [item.find(f"{_MAIN}t")] + [run.find(f"{_MAIN}t") for run in item.iter(f"{_MAIN}r")]
        strings.append("".join(run.text or "" for run in runs if run is not None))
    return strings


def _date_styles(archive: zipfile.ZipFile, names: set[str]) -> tuple[set[int], set[int], Any]:
    """Style indexes formatted as dates and as durations, and the workbook's date epoch."""

    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    properties = workbook.find(f"{_MAIN}workbookPr")
    mac = properties is not None and properties.get("date1904") in ("1", "true")
    epoch = CALENDAR_MAC_1904 if mac else CALENDAR_WINDOWS_1900
    if "xl/styles.xml" not in names:
        return set(), set(), epoch
    styles = ElementTree.fromstring(archive.read("xl/styles.xml"))
    formats: dict[int, str] = dict(BUILTIN_FORMATS)
    for number_format in styles.iter(f"{_MAIN}numFmt"):
        formats[int(number_format.get("numFmtId", "0"))] = number_format.get("formatCode", "")
    cell_formats = styles.find(f"{_MAIN}cellXfs")
    dates, durations = set(), set()
    for index, xf in enumerate(() if cell_formats is None else cell_formats.iter(f"{_MAIN}xf")):
        code = formats.get(int(xf.get("numFmtId", "0")), "")
        if is_date_format(code):
            dates.add(index)
            if is_timedelta_format(code):
                durations.add(index)
    return dates, durations, epoch


def _cell_value(
    element: ElementTree.Element,
    strings: list[str],
    dates: set[int],
    durations: set[int],
    epoch: Any,
) -> Any:
    kind = element.get("t", "n")
    if kind == "inlineStr":
        return "".join(text.text or "" for text in element.iter(f"{_MAIN}t")) or None
    raw = element.findtext(f"{_MAIN}v")
    if raw is None:
        return None
    if kind == "s":
        return strings[int(raw)]
    if kind in ("str", "e"):
        return raw
    if kind == "b":
        return raw in ("1", "true")
    if kind == "d":
        return datetime.datetime.fromisoformat(raw)
    number: int | float = float(raw) if any(c in raw for c in ".eE") else int(raw)
    style = int(element.get("s", "0"))
    if style in dates:
        return from_excel(number, epoch, timedelta=style in durations)
    return number
