#!/usr/bin/env python3
"""Keep the agent leaderboards: add an agent's results and re-render them.

There are two boards, each a file under leaderboard/: ``hard`` (the main board, 12 hard
cases) and ``pilot`` (3 small cases). An agent is added from a run folder that holds every
case of the board.

Examples:
    # add one agent from a run of the hard set, then re-render
    python scripts/leaderboard.py add results/runs/my-run --agent codex \\
        --name Codex --model GPT-5.4 --interface "Coding agent · Codex CLI"

    # the same for the pilot board
    python scripts/leaderboard.py add results/runs/pilot --board pilot --agent codex ...

    # re-render assets/leaderboard.svg, README.md and docs/leaderboard.md
    python scripts/leaderboard.py render
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.leaderboard import (  # noqa: E402
    entry_from_records,
    label,
    load_entries,
    ranked,
    replace_between,
    save_entries,
    svg_card,
    table,
    upsert,
)

BOARDS = {
    "hard": ROOT / "leaderboard" / "hard.json",
    "pilot": ROOT / "leaderboard" / "pilot.json",
}
CARD = ROOT / "assets" / "leaderboard.svg"
README = ROOT / "README.md"
DOC = ROOT / "docs" / "leaderboard.md"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="add or update one agent from a run folder")
    add.add_argument("run_dir", type=Path, help="results/runs/<run-id>")
    add.add_argument("--board", choices=tuple(BOARDS), default="hard", help="board to add to")
    add.add_argument("--agent", required=True, help="agent folder name inside the run")
    add.add_argument("--name", required=True, help="agent or product name, e.g. Codex")
    add.add_argument("--model", default="", help="model name, e.g. GLM-5.2")
    add.add_argument("--interface", required=True, help='e.g. "Coding agent · Codex CLI"')
    add.add_argument("--note", default="", help="optional note shown under the table")
    commands.add_parser("render", help="re-render the card, README.md and docs/leaderboard.md")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    boards = {name: load_entries(path) for name, path in BOARDS.items()}
    if args.command == "add":
        data = boards[args.board]
        summary = json.loads((args.run_dir / "summary.json").read_text(encoding="utf-8"))
        try:
            stats = entry_from_records(summary["records"], args.agent, data["cases"])
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
        entry = {
            "name": args.name,
            "model": args.model,
            "interface": args.interface,
            **stats,
            "engine": summary.get("engine", ""),
            "date": (summary.get("written_at") or date.today().isoformat())[:10],
            "run": args.run_dir.name,
            "note": args.note,
        }
        data["entries"] = upsert(data["entries"], entry)
        save_entries(BOARDS[args.board], data)
        print(f"{args.name}: {stats['real_models']}/{stats['cases']} real models ({args.board})")
    render(boards)
    print(table(boards["hard"]["entries"]))
    return 0


def render(boards: dict[str, dict]) -> None:
    main_board = boards["hard"]
    n = len(main_board["cases"])
    updated = max(e["date"] for e in main_board["entries"])
    subtitle = f"AI agents on {n} hard cases: LBO, debt waterfall, DCF, M&A and more"
    CARD.write_text(
        svg_card(main_board["entries"], main_board["cases"], updated, subtitle), encoding="utf-8"
    )
    rows = table(main_board["entries"])
    top = ", ".join(
        f"{label(e)} {e['real_models']}/{e['cases']}" for e in ranked(main_board["entries"])[:3]
    )
    block = (
        f'<p align="center"><img src="assets/leaderboard.svg" width="100%" '
        f'alt="Tickmark leaderboard, real models on {n} hard cases: {top}. '
        f'Full table below."></p>\n\n'
        f"<details>\n<summary>Table view</summary>\n\n{rows}\n\n</details>"
    )
    README.write_text(replace_between(README.read_text(encoding="utf-8"), block), encoding="utf-8")
    DOC.write_text(_document(boards), encoding="utf-8")


def _board_section(data: dict) -> str:
    details = ["| Agent | Engine | Date | Run |", "|---|---|---|---|"]
    for e in ranked(data["entries"]):
        details.append(f"| {label(e)} | {e['engine']} | {e['date']} | `{e['run']}` |")
    notes = [f"- **{label(e)}**: {e['note']}" for e in ranked(data["entries"]) if e.get("note")]
    return f"{table(data['entries'])}\n\n{chr(10).join(details)}\n\n{chr(10).join(notes)}"


def _document(boards: dict[str, dict]) -> str:
    hard, pilot = boards["hard"], boards["pilot"]
    hard_cases = ", ".join(f"`{case}`" for case in hard["cases"])
    pilot_cases = ", ".join(f"`{case}`" for case in pilot["cases"])
    return f"""# Agent leaderboard

There are two boards. Both are generated by `scripts/leaderboard.py` from the files in
[`leaderboard/`](../leaderboard/); do not edit the tables by hand.

- **Hard cases**, the main board shown in the README: {len(hard["cases"])} cases chosen for
  difficulty ({hard_cases}). They are the five cases whose reference formulas branch the
  most (LBO debt schedules, cash sweeps and debt waterfalls) plus the largest and
  multi-sheet models, and they cover 8 of the 10 model families.
- **Pilot cases**: three small cases ({pilot_cases}) for a quick end-to-end run. Five agents
  pass all three, so this board no longer separates the strongest ones.

<p align="center"><img src="../assets/leaderboard.svg" width="100%" alt="Leaderboard card"></p>

- **Real models**: cases passed, meaning every number right and every audit check passed.
- **Right numbers**: cases with every number right, which is all a value-only benchmark
  checks.
- **Checks passed**: share of all audit checks passed across the cases (7 per case, equal
  weight).
- **Values right**, **Formulas**, **Traceable**: mean share of target cells with the right
  value, holding a formula, and tracing back to the declared inputs.
- **Time per case**: median wall-clock seconds per case. On free tiers this includes
  provider queueing and rate-limit waits, so compare speed with care.

Ranked by real models, then checks passed, then right numbers; agents equal on all three
share a rank. An agent joins a board once it has a graded result on every case of that
board.

## Hard cases

{_board_section(hard)}

## Pilot cases

{_board_section(pilot)}

## Add an agent

1. Run the hard set, for any configured agent or any `<provider>:<model>`
   ([docs/agents.md](agents.md)):

   ```bash
   uv run python scripts/run_real_agent_suite.py --set hard \\
       --agents openrouter:<model-id> --run-id my-agent
   ```

2. Add it and re-render the card and tables:

   ```bash
   uv run python scripts/leaderboard.py add results/runs/my-agent --agent <folder> \\
       --name "<Agent>" --model "<Model>" --interface "Chat API · OpenRouter"
   ```

   `<folder>` is the agent's folder inside the run, for example
   `openrouter-z-ai-glm-5.2-free`. For the pilot board, run with `--set pilot` and add
   with `--board pilot`.

3. Open a pull request with `leaderboard/`, `assets/leaderboard.svg`, `README.md` and
   `docs/leaderboard.md`.
"""


if __name__ == "__main__":
    raise SystemExit(main())
