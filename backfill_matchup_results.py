"""
Backfill a `results` column (W / L / T) into historical `data/YYYY-MM-DD_matchups.csv`.

Skips files whose header already includes `results`, and skips the US Eastern
calendar day of "today" so the live slate is left unchanged. Uses MLB Stats API schedule data
(same source as main.py).
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from main import _norm_team_name, eastern_date_today, fetch_schedule_games

DATE_STEM = re.compile(r"^(\d{4}-\d{2}-\d{2})_matchups\.csv$")


def _games_by_pk(games: list[dict]) -> dict[int, dict]:
    return {int(g["gamePk"]): g for g in games}


def _side_matches_team(side: dict, team: str) -> bool:
    name = (side.get("team") or {}).get("name") or ""
    if name == team:
        return True
    return _norm_team_name(name) == _norm_team_name(team)


def _result_for_team(game: dict, team: str) -> str:
    status = (game.get("status") or {}).get("detailedState") or ""
    if status in {"Cancelled", "Canceled", "Postponed"}:
        return ""
    abs_state = (game.get("status") or {}).get("abstractGameState") or ""
    if abs_state != "Final" and status != "Final":
        return ""
    if game.get("isTie"):
        return "T"

    away = game["teams"]["away"]
    home = game["teams"]["home"]
    if _side_matches_team(away, team):
        w = away.get("isWinner")
        if w is True:
            return "W"
        if w is False and home.get("isWinner") is True:
            return "L"
        return ""
    if _side_matches_team(home, team):
        w = home.get("isWinner")
        if w is True:
            return "W"
        if w is False and away.get("isWinner") is True:
            return "L"
        return ""
    return ""


def _matchup_files(data_dir: Path) -> list[tuple[date, Path]]:
    out: list[tuple[date, Path]] = []
    for path in sorted(data_dir.glob("*_matchups.csv")):
        m = DATE_STEM.match(path.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        out.append((d, path))
    return out


def backfill(data_dir: Path, today: date | None = None) -> None:
    today = today or eastern_date_today()
    for on, path in _matchup_files(data_dir):
        if on >= today:
            continue
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            continue
        header = rows[0]
        if any(h.strip().lower() == "results" for h in header):
            print(f"skip (already has results): {path.name}")
            continue
        games = fetch_schedule_games(on)
        by_pk = _games_by_pk(games)

        new_header = [*header, "results"]
        body = rows[1:]
        # locate team column for result lookup
        try:
            i_game = header.index("game_pk")
            i_team = header.index("team")
        except ValueError:
            print(f"skip (missing game_pk/team columns): {path.name}")
            continue

        new_body: list[list[str]] = []
        for row in body:
            if len(row) < max(i_game, i_team) + 1:
                new_body.append([*row, ""])
                continue
            try:
                pk = int(row[i_game])
            except ValueError:
                new_body.append([*row, ""])
                continue
            g = by_pk.get(pk)
            res = _result_for_team(g, row[i_team]) if g else ""
            new_body.append([*row, res])

        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(new_header)
            w.writerows(new_body)
        print(f"updated: {path.name} ({len(new_body)} rows)")


def main() -> None:
    data_dir = Path("data")
    if not data_dir.is_dir():
        raise SystemExit("data/ directory not found (run from project root)")
    backfill(data_dir)


if __name__ == "__main__":
    main()
