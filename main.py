"""
Daily MLB slate: team hitting_obp and pitching_obp (OBP allowed), matchup nets,
ESPN moneylines. Uses MLB Stats API + ESPN pickcenter (see README).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

STATS_BASE = "https://statsapi.mlb.com/api/v1"
ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
)
ESPN_SUMMARY = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"
)

# US Eastern — MLB slate and dated output files follow this calendar day.
_EASTERN_TZ = ZoneInfo("America/New_York")


def eastern_date_today() -> date:
    """Current calendar date in America/New_York (EST/EDT)."""
    return datetime.now(_EASTERN_TZ).date()


def _fetch_json(url: str) -> dict | list:
    with urlopen(url) as resp:
        return json.load(resp)


def _parse_obp(raw: str) -> float:
    return float(raw)


def _fetch_team_obp_map(season: int, group: str) -> dict[int, float]:
    url = (
        f"{STATS_BASE}/teams/stats?"
        f"season={season}&group={group}&stats=season&sportId=1"
    )
    payload = _fetch_json(url)
    splits = payload["stats"][0]["splits"]
    return {s["team"]["id"]: _parse_obp(s["stat"]["obp"]) for s in splits}


def fetch_team_hitting_and_pitching_obp(
    season: int,
) -> tuple[dict[int, float], dict[int, float], list[dict]]:
    """
    Returns (team_id -> hitting OBP), (team_id -> pitching OBP allowed to
    opponents — exposed as pitching_obp in CSVs), and rows for the team snapshot.
    """
    hitting_url = (
        f"{STATS_BASE}/teams/stats?"
        f"season={season}&group=hitting&stats=season&sportId=1"
    )
    payload_h = _fetch_json(hitting_url)
    splits_h = payload_h["stats"][0]["splits"]
    hitting: dict[int, float] = {}
    tid_to_name: dict[int, str] = {}
    for s in splits_h:
        tid = s["team"]["id"]
        hitting[tid] = _parse_obp(s["stat"]["obp"])
        tid_to_name[tid] = s["team"]["name"]

    pitching_allowed = _fetch_team_obp_map(season, "pitching")

    rows: list[dict] = []
    for tid in sorted(tid_to_name, key=lambda i: tid_to_name[i]):
        if tid not in pitching_allowed:
            continue
        rows.append(
            {
                "team_id": tid,
                "team_name": tid_to_name[tid],
                "hitting_obp": hitting[tid],
                "pitching_obp": pitching_allowed[tid],
            }
        )
    return hitting, pitching_allowed, rows


def write_team_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["team_id", "team_name", "hitting_obp", "pitching_obp"]
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "team_id": r["team_id"],
                    "team_name": r["team_name"],
                    "hitting_obp": f"{r['hitting_obp']:.3f}",
                    "pitching_obp": f"{r['pitching_obp']:.3f}",
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
    hitting_obp: dict[int, float],
    pitching_obp: dict[int, float],
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
        if (
            aid not in hitting_obp
            or hid not in hitting_obp
            or aid not in pitching_obp
            or hid not in pitching_obp
        ):
            continue
        a_hit, h_hit = hitting_obp[aid], hitting_obp[hid]
        a_p, h_p = pitching_obp[aid], pitching_obp[hid]
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
                "hitting_obp": a_hit,
                "opponent_hitting_obp": h_hit,
                "pitching_obp": a_p,
                "opponent_pitching_obp": h_p,
                "net_hitting_obp": round(a_hit - h_hit, 4),
                "net_pitching_obp": round(a_p - h_p, 4),
                "odds": odds_role(a_line, h_line),
            }
        )
        out.append(
            {
                **base,
                "team": h_name,
                "opponent": a_name,
                "hitting_obp": h_hit,
                "opponent_hitting_obp": a_hit,
                "pitching_obp": h_p,
                "opponent_pitching_obp": a_p,
                "net_hitting_obp": round(h_hit - a_hit, 4),
                "net_pitching_obp": round(h_p - a_p, 4),
                "odds": odds_role(h_line, a_line),
            }
        )
    out.sort(key=lambda r: (-r["net_hitting_obp"], r["net_pitching_obp"]))
    return out


def write_matchup_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "game_pk",
        "team",
        "opponent",
        "hitting_obp",
        "opponent_hitting_obp",
        "pitching_obp",
        "opponent_pitching_obp",
        "net_hitting_obp",
        "net_pitching_obp",
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
                    "hitting_obp": f"{r['hitting_obp']:.3f}",
                    "opponent_hitting_obp": f"{r['opponent_hitting_obp']:.3f}",
                    "pitching_obp": f"{r['pitching_obp']:.3f}",
                    "opponent_pitching_obp": f"{r['opponent_pitching_obp']:.3f}",
                    "net_hitting_obp": f"{r['net_hitting_obp']:.4f}",
                    "net_pitching_obp": f"{r['net_pitching_obp']:.4f}",
                    "odds": r["odds"],
                }
            )


def run_pipeline(data_dir: Path, today: date | None = None) -> None:
    today = today or eastern_date_today()
    season = today.year

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
        out_csv_spread=results_dir / "historic_matchup_spread_by_odds.csv",
        out_png_spread=results_dir / "historic_matchup_spread_winrate.png",
    )

    team_csv = data_dir / f"{today.isoformat()}.csv"
    matchup_csv = data_dir / f"{today.isoformat()}_matchups.csv"

    hitting_obp, pitching_obp_map, team_rows = fetch_team_hitting_and_pitching_obp(
        season
    )
    write_team_csv(team_csv, team_rows)

    games = fetch_schedule_games(today)
    espn_ml = fetch_espn_moneylines_by_team_pair(today)
    matchup_rows = matchup_rows_for_games(games, hitting_obp, pitching_obp_map, espn_ml)
    write_matchup_csv(matchup_csv, matchup_rows)

    print(f"Wrote {team_csv} ({len(team_rows)} teams)")
    print(
        f"Wrote {matchup_csv} ({len(matchup_rows)} team-sides, "
        "sorted by net_hitting_obp desc, then net_pitching_obp asc)"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--storage",
        choices=("local", "gcs"),
        default="local",
        help="local: read/write ./data. gcs: sync data/ prefix from/to a bucket.",
    )
    p.add_argument(
        "--gcs-bucket",
        default=os.environ.get("GCS_BUCKET", ""),
        metavar="NAME",
        help="GCS bucket name (required for --storage gcs; else env GCS_BUCKET).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.storage == "local":
        run_pipeline(Path("data"))
        return

    bucket = (args.gcs_bucket or "").strip()
    if not bucket:
        print(
            "--gcs-bucket or GCS_BUCKET is required when --storage gcs",
            file=sys.stderr,
        )
        raise SystemExit(2)

    from gcs_sync import download_data_prefix, upload_data_tree

    tmp = Path(tempfile.mkdtemp(prefix="mlb-gameday-data-"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True)
    try:
        download_data_prefix(bucket, data_dir)
        run_pipeline(data_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    upload_data_tree(bucket, data_dir)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Synced data/ to gs://{bucket}/data/")


if __name__ == "__main__":
    main()
