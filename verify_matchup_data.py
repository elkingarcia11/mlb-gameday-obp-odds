"""
Sanity-check historic matchup CSVs: internal net OBP math (or legacy matchup),
two rows per game, complementary W/L, and (optional) results vs MLB API samples.

Run from project root:

    python3 verify_matchup_data.py
    python3 verify_matchup_data.py --api-sample 3
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from backfill_matchup_results import _result_for_team
from main import fetch_schedule_games

DATE_STEM = re.compile(r"^(\d{4}-\d{2}-\d{2})_matchups\.csv$")
_MATCHUP_TOL = 1e-5


def _parse_date_from_matchup_path(path: Path) -> date | None:
    m = DATE_STEM.match(path.name)
    if not m:
        return None
    return date.fromisoformat(m.group(1))


def verify_csv_internal(data_dir: Path) -> list[str]:
    """Return list of error strings; empty means all checks passed."""
    errors: list[str] = []

    for path in sorted(data_dir.glob("*_matchups.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            if not any(h.strip().lower() == "results" for h in fields):
                continue
            rows = list(reader)

        lc = {h.strip().lower(): h for h in fields}
        use_net = "net_hitting_obp" in lc
        use_legacy = (not use_net) and "matchup" in lc and "obp" in lc

        games: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            pk = row.get("game_pk", "").strip()
            if pk:
                games[pk].append(row)

            def col(name: str) -> str:
                k = lc.get(name.lower())
                return (row.get(k) or "").strip() if k else ""

            try:
                if use_net:
                    h_obp = float(col("hitting_obp"))
                    oh_obp = float(col("opponent_hitting_obp"))
                    nh = float(col("net_hitting_obp"))
                    p_obp = float(col("pitching_obp"))
                    op_obp = float(col("opponent_pitching_obp"))
                    np = float(col("net_pitching_obp"))
                elif use_legacy:
                    obp = float(col("obp"))
                    oobp = float(col("opponent_obp"))
                    mu = float(col("matchup"))
                else:
                    continue
            except ValueError as e:
                errors.append(f"{path.name} row team={row.get('team')!r}: parse error {e}")
                continue

            if use_net:
                if abs(h_obp - oh_obp - nh) > _MATCHUP_TOL:
                    errors.append(
                        f"{path.name} game_pk={row.get('game_pk')} team={row.get('team')!r}: "
                        f"net_hitting_obp {nh} != hitting_obp - opponent_hitting_obp "
                        f"({h_obp - oh_obp})"
                    )
                if abs(p_obp - op_obp - np) > _MATCHUP_TOL:
                    errors.append(
                        f"{path.name} game_pk={row.get('game_pk')} team={row.get('team')!r}: "
                        f"net_pitching_obp {np} != pitching_obp - opponent_pitching_obp "
                        f"({p_obp - op_obp})"
                    )
            elif use_legacy:
                diff = obp - oobp
                if abs(diff - mu) > _MATCHUP_TOL:
                    errors.append(
                        f"{path.name} game_pk={row.get('game_pk')} team={row.get('team')!r}: "
                        f"matchup {mu} != obp - opponent_obp ({diff})"
                    )

        for pk, rs in games.items():
            if len(rs) != 2:
                errors.append(f"{path.name} game_pk={pk}: expected 2 rows, got {len(rs)}")
                continue
            ra, rb = rs[0], rs[1]
            res_a = (ra.get("results") or "").strip().upper()
            res_b = (rb.get("results") or "").strip().upper()
            if not res_a and not res_b:
                continue
            if {res_a, res_b} == {"W", "L"}:
                pass
            elif res_a == "T" and res_b == "T":
                pass
            else:
                errors.append(
                    f"{path.name} game_pk={pk}: results not complementary W/L or T/T: "
                    f"{res_a!r}, {res_b!r}"
                )

            oa = (ra.get("odds") or "").strip().lower()
            ob = (rb.get("odds") or "").strip().lower()
            if {oa, ob} == {"favorite", "not favorite"}:
                pass
            elif oa == "equal" and ob == "equal":
                pass
            elif oa == "unknown" and ob == "unknown":
                pass
            elif oa == "unknown" or ob == "unknown":
                pass
            else:
                errors.append(
                    f"{path.name} game_pk={pk}: unexpected odds pair {oa!r}, {ob!r}"
                )

    return errors


def verify_api_sample(data_dir: Path, n_per_file: int) -> list[str]:
    """Compare CSV `results` to MLB API for up to n_per_file games per dated file."""
    errors: list[str] = []
    for path in sorted(data_dir.glob("*_matchups.csv")):
        on = _parse_date_from_matchup_path(path)
        if on is None:
            continue
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not any(h.strip().lower() == "results" for h in (reader.fieldnames or [])):
                continue
            rows = list(reader)
        if not rows:
            continue

        games = fetch_schedule_games(on)
        by_pk = {int(g["gamePk"]): g for g in games}

        seen_pk: set[int] = set()
        checked = 0
        for row in rows:
            if checked >= n_per_file:
                break
            try:
                pk = int(row["game_pk"])
            except (KeyError, ValueError):
                continue
            if pk in seen_pk:
                continue
            seen_pk.add(pk)
            g = by_pk.get(pk)
            if not g:
                errors.append(f"{path.name} game_pk={pk}: not in API schedule for {on}")
                checked += 1
                continue
            api_res = _result_for_team(g, row["team"])
            csv_res = (row.get("results") or "").strip().upper()
            if api_res and csv_res and api_res != csv_res:
                errors.append(
                    f"{path.name} game_pk={pk} team={row.get('team')!r}: "
                    f"CSV results={csv_res!r} API={api_res!r}"
                )
            checked += 1

    return errors


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory containing *_matchups.csv (default: data)",
    )
    p.add_argument(
        "--api-sample",
        type=int,
        default=0,
        metavar="N",
        help="Also check first N distinct game_pk per dated file against MLB API (0=skip)",
    )
    args = p.parse_args()
    if not args.data_dir.is_dir():
        raise SystemExit(f"Not a directory: {args.data_dir}")

    internal = verify_csv_internal(args.data_dir)
    if internal:
        print("INTERNAL CSV CHECKS FAILED")
        for e in internal:
            print(" ", e)
        raise SystemExit(1)
    print(
        "OK: net OBP math (or legacy matchup); two rows per game; W/L pairs; "
        "favorite/not favorite pairs."
    )

    if args.api_sample > 0:
        api_err = verify_api_sample(args.data_dir, args.api_sample)
        if api_err:
            print("API SAMPLE CHECK FAILED")
            for e in api_err:
                print(" ", e)
            raise SystemExit(1)
        print(f"OK: API spot-check (up to {args.api_sample} games per file with results).")


if __name__ == "__main__":
    main()
