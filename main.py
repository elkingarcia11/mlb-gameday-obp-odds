"""
MLB gameday odds edge finder: team OBP vs opponents and moneyline favorite labels.

Uses MLB Stats API (statsapi.mlb.com) for OBP and schedule; ESPN game summary
pickcenter (typically DraftKings) for American moneylines, matched by team names.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

STATS_BASE = "https://statsapi.mlb.com/api/v1"
ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
)
ESPN_SUMMARY = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"
)


def _fetch_json(url: str) -> dict | list:
    with urlopen(url) as resp:
        return json.load(resp)


def _parse_obp(raw: str) -> float:
    return float(raw)


def fetch_team_obp_by_id(season: int) -> tuple[dict[int, float], list[dict]]:
    """Returns (team_id -> obp) and rows suitable for CSV."""
    url = (
        f"{STATS_BASE}/teams/stats?"
        f"season={season}&group=hitting&stats=season&sportId=1"
    )
    payload = _fetch_json(url)
    splits = payload["stats"][0]["splits"]
    by_id: dict[int, float] = {}
    rows: list[dict] = []
    for s in splits:
        tid = s["team"]["id"]
        name = s["team"]["name"]
        obp = _parse_obp(s["stat"]["obp"])
        by_id[tid] = obp
        rows.append({"team_id": tid, "team_name": name, "obp": obp})
    rows.sort(key=lambda r: r["team_name"])
    return by_id, rows


def write_team_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["team_id", "team_name", "obp"])
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "team_id": r["team_id"],
                    "team_name": r["team_name"],
                    "obp": f"{r['obp']:.3f}",
                }
            )


def fetch_schedule_games(on: date) -> list[dict]:
    url = f"{STATS_BASE}/schedule?sportId=1&date={on.isoformat()}"
    payload = _fetch_json(url)
    games: list[dict] = []
    for d in payload.get("dates", []):
        games.extend(d.get("games", []))
    return games


def _norm_team_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _pickcenter_moneylines(pickcenter: list[dict] | None) -> tuple[int | None, int | None]:
    """Return (away_moneyline, home_moneyline) from first usable book row."""
    if not pickcenter:
        return None, None
    for row in pickcenter:
        away = row.get("awayTeamOdds") or {}
        home = row.get("homeTeamOdds") or {}
        a_ml = away.get("moneyLine")
        h_ml = home.get("moneyLine")
        if a_ml is not None and h_ml is not None:
            return int(a_ml), int(h_ml)
    return None, None


def fetch_espn_moneylines_by_team_pair(on: date) -> dict[frozenset[str], dict[str, int]]:
    """
    Map frozenset({team_a, team_b}) -> {display_name: american_moneyline}
    using ESPN scoreboard + per-game summary pickcenter.
    """
    ymd = on.strftime("%Y%m%d")
    url = f"{ESPN_SCOREBOARD}?dates={ymd}"
    try:
        payload = _fetch_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}

    out: dict[frozenset[str], dict[str, int]] = {}
    for event in payload.get("events") or []:
        eid = event.get("id")
        comps = (event.get("competitions") or [{}])[0].get("competitors") or []
        by_side: dict[str, str] = {}
        for c in comps:
            side = c.get("homeAway")
            team = c.get("team") or {}
            name = team.get("displayName") or team.get("name")
            if side in ("home", "away") and name:
                by_side[side] = name
        away_n = by_side.get("away")
        home_n = by_side.get("home")
        if not eid or not away_n or not home_n:
            continue
        try:
            summary = _fetch_json(f"{ESPN_SUMMARY}?event={eid}")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict):
            continue
        a_ml, h_ml = _pickcenter_moneylines(summary.get("pickcenter"))
        if a_ml is None or h_ml is None:
            continue
        key = frozenset({away_n, home_n})
        out[key] = {away_n: a_ml, home_n: h_ml}
    return out


def _moneylines_for_mlb_game(
    away_name: str, home_name: str, espn: dict[frozenset[str], dict[str, int]]
) -> dict[str, int] | None:
    key = frozenset({away_name, home_name})
    exact = espn.get(key)
    if exact is not None:
        return exact
    na, nh = _norm_team_name(away_name), _norm_team_name(home_name)
    for pair_key, lines in espn.items():
        names = list(pair_key)
        if len(names) != 2:
            continue
        if {_norm_team_name(names[0]), _norm_team_name(names[1])} == {na, nh}:
            # Return lines keyed by MLB spellings so row lookup works.
            rev = {_norm_team_name(n): v for n, v in lines.items()}
            return {
                away_name: rev[na],
                home_name: rev[nh],
            }
    return None


def odds_role(team_ml: int | None, opp_ml: int | None) -> str:
    if team_ml is None or opp_ml is None:
        return "unknown"
    if team_ml == opp_ml:
        return "equal"
    if team_ml < opp_ml:
        return "favorite"
    return "not favorite"


def matchup_rows_for_games(
    games: list[dict],
    team_obp: dict[int, float],
    espn_moneylines: dict[frozenset[str], dict[str, int]] | None = None,
) -> list[dict]:
    skip = {"Cancelled", "Canceled", "Postponed"}
    espn_moneylines = espn_moneylines or {}
    out: list[dict] = []
    for g in games:
        if g["status"]["detailedState"] in skip:
            continue
        away = g["teams"]["away"]["team"]
        home = g["teams"]["home"]["team"]
        aid, hid = away["id"], home["id"]
        if aid not in team_obp or hid not in team_obp:
            continue
        a_obp, h_obp = team_obp[aid], team_obp[hid]
        a_name, h_name = away["name"], home["name"]
        lines_by_name = _moneylines_for_mlb_game(a_name, h_name, espn_moneylines)

        def line_for(team: str) -> int | None:
            if not lines_by_name:
                return None
            v = lines_by_name.get(team)
            if v is not None:
                return v
            nt = _norm_team_name(team)
            for n, ml in lines_by_name.items():
                if _norm_team_name(n) == nt:
                    return ml
            return None

        base = {"game_pk": g["gamePk"]}
        a_line, h_line = line_for(a_name), line_for(h_name)
        out.append(
            {
                **base,
                "team": a_name,
                "opponent": h_name,
                "obp": a_obp,
                "opponent_obp": h_obp,
                "matchup": round(a_obp - h_obp, 4),
                "odds": odds_role(a_line, h_line),
            }
        )
        out.append(
            {
                **base,
                "team": h_name,
                "opponent": a_name,
                "obp": h_obp,
                "opponent_obp": a_obp,
                "matchup": round(h_obp - a_obp, 4),
                "odds": odds_role(h_line, a_line),
            }
        )
    out.sort(key=lambda r: r["matchup"], reverse=True)
    return out


def write_matchup_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "game_pk",
        "team",
        "opponent",
        "obp",
        "opponent_obp",
        "matchup",
        "odds",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "game_pk": r["game_pk"],
                    "team": r["team"],
                    "opponent": r["opponent"],
                    "obp": f"{r['obp']:.3f}",
                    "opponent_obp": f"{r['opponent_obp']:.3f}",
                    "matchup": f"{r['matchup']:.4f}",
                    "odds": r["odds"],
                }
            )


def main() -> None:
    today = date.today()
    season = today.year
    data_dir = Path("data")

    # Backfill W/L/T on past matchup CSVs before writing today's files.
    from backfill_matchup_results import backfill

    backfill(data_dir, today=today)

    from analyze_historic_favorites import run as run_historic_matchup_analysis

    results_dir = data_dir / "results"
    run_historic_matchup_analysis(
        data_dir,
        results_dir / "historic_matchup_odds_results.csv",
        results_dir / "historic_matchup_odds_results.txt",
        {"csv", "txt"},
        plot=True,
        out_png=results_dir / "historic_matchup_odds_results.png",
    )

    team_csv = data_dir / f"{today.isoformat()}.csv"
    matchup_csv = data_dir / f"{today.isoformat()}_matchups.csv"

    team_obp, team_rows = fetch_team_obp_by_id(season)
    write_team_csv(team_csv, team_rows)

    games = fetch_schedule_games(today)
    espn_ml = fetch_espn_moneylines_by_team_pair(today)
    matchup_rows = matchup_rows_for_games(games, team_obp, espn_ml)
    write_matchup_csv(matchup_csv, matchup_rows)

    print(f"Wrote {team_csv} ({len(team_rows)} teams)")
    print(f"Wrote {matchup_csv} ({len(matchup_rows)} team-sides, sorted by matchup)")


if __name__ == "__main__":
    main()
