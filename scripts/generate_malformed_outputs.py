#!/usr/bin/env python3
"""Generate controlled bad submissions from selected benchmark golden workbooks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.cases import load_case  # noqa: E402
from tickmark.malformed_outputs import generate_malformed_outputs  # noqa: E402


def _case_dirs(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if (path / "case.json").exists():
            found.append(path)
            continue
        found.extend(sorted(child for child in path.iterdir() if (child / "case.json").exists()))
    return list(dict.fromkeys(found))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        nargs="+",
        type=Path,
        default=[Path("data/cases/16_04")],
        help="case folder(s), or a parent folder containing case folders (default: 16_04)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("results/malformed_outputs"),
        help="root directory; each case is written to <root>/<case-id>",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    case_dirs = _case_dirs(args.case)
    if not case_dirs:
        raise SystemExit("No case.json files found in the supplied --case paths.")

    total = 0
    for case_dir in case_dirs:
        case = load_case(case_dir)
        destination = args.output_root / case.case_id
        generated = generate_malformed_outputs(case, destination)
        total += len(generated)
        print(f"{case.case_id}: generated {len(generated)} outputs in {destination}")
    print(f"Generated {total} malformed workbook(s) for {len(case_dirs)} case(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
