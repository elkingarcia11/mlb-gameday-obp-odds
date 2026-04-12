"""
Historic matchup CSV analysis: cross-tab `matchup` (OBP edge) vs `odds` role vs `results`.

For each row in `data/YYYY-MM-DD_matchups.csv` (files that already have a `results`
column), buckets are:

- **odds**: moneyline role from the `odds` column — ``favorite``, ``not favorite``,
  or ``other`` (e.g. unknown / equal).
- **matchup sign**: numeric ``matchup`` column — less than 0, equal to 0, greater
  than 0, or unparsable (**unknown**).

Win rate is **W / (W+L)** only; ties and blank results are counted but excluded
from that denominator.

Writes ``data/results/historic_matchup_odds_results.csv`` and ``.txt`` by default.
Unless ``--no-plot`` is passed, also writes ``data/results/historic_matchup_odds_results.png``
(2D heatmap; requires matplotlib).
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Bucket:
    wins: int = 0
    losses: int = 0
    ties: int = 0
    no_result: int = 0

    def decided(self) -> int:
        return self.wins + self.losses

    def win_rate(self) -> float | None:
        d = self.decided()
        if d == 0:
            return None
        return self.wins / d


def _parse_matchup(raw: str) -> float | None:
    try:
        return float((raw or "").strip())
    except ValueError:
        return None


def _parse_result(raw: str) -> str:
    s = (raw or "").strip().upper()
    if s in {"W", "L", "T"}:
        return s
    return ""


def _odds_role(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s == "favorite":
        return "favorite"
    if s == "not favorite":
        return "not_favorite"
    return "other"


def _edge_bucket(mu: float | None) -> str:
    if mu is None:
        return "unknown"
    if mu > 0:
        return "gt0"
    if mu < 0:
        return "lt0"
    return "eq0"


def _add_outcome(b: Bucket, res: str) -> None:
    if res == "W":
        b.wins += 1
    elif res == "L":
        b.losses += 1
    elif res == "T":
        b.ties += 1
    else:
        b.no_result += 1


def _collect(
    data_dir: Path,
) -> tuple[dict[tuple[str, str], Bucket], int, list[str]]:
    """
    Returns ((odds_role, edge_bucket) -> Bucket, rows_in_usable_files, missing_results_files).
    """
    grid: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    rows_in_usable_files = 0
    missing_results: list[str] = []

    paths = sorted(data_dir.glob("*_matchups.csv"))
    for path in paths:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            if not fields:
                continue
            if not any(h.strip().lower() == "results" for h in fields):
                missing_results.append(path.name)
                continue
            for row in reader:
                rows_in_usable_files += 1
                role = _odds_role(row.get("odds", ""))
                edge = _edge_bucket(_parse_matchup(row.get("matchup", "")))
                res = _parse_result(row.get("results", ""))
                _add_outcome(grid[(role, edge)], res)

    return dict(grid), rows_in_usable_files, missing_results


def _rate(b: Bucket) -> str:
    r = b.win_rate()
    return "" if r is None else f"{r:.4f}"


ODDS_LABEL = {
    "favorite": "favorite (moneyline)",
    "not_favorite": "not favorite (moneyline)",
    "other": "other odds label (unknown / equal / …)",
}

EDGE_LABEL = {
    "lt0": "matchup < 0",
    "eq0": "matchup = 0",
    "gt0": "matchup > 0",
    "unknown": "matchup unparsable",
}

EDGE_ORDER = ("lt0", "eq0", "gt0", "unknown")
ODDS_ORDER_PRIMARY = ("favorite", "not_favorite")


def _iter_rows(grid: dict[tuple[str, str], Bucket]) -> list[tuple[str, str, Bucket]]:
    """Stable row order for CSV/TXT."""
    rows: list[tuple[str, str, Bucket]] = []
    for role in (*ODDS_ORDER_PRIMARY, "other"):
        for edge in EDGE_ORDER:
            b = grid.get((role, edge)) or Bucket()
            rows.append((role, edge, b))
    return rows


def _write_csv(path: Path, grid: dict[tuple[str, str], Bucket]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "odds_role",
        "matchup_sign",
        "description",
        "wins",
        "losses",
        "ties",
        "no_result",
        "decided_games",
        "win_rate_wl_only",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for role, edge, b in _iter_rows(grid):
            desc = f"{ODDS_LABEL.get(role, role)}; {EDGE_LABEL.get(edge, edge)}"
            w.writerow(
                {
                    "odds_role": role,
                    "matchup_sign": edge,
                    "description": desc,
                    "wins": b.wins,
                    "losses": b.losses,
                    "ties": b.ties,
                    "no_result": b.no_result,
                    "decided_games": b.decided(),
                    "win_rate_wl_only": _rate(b),
                }
            )


def _write_txt(path: Path, grid: dict[tuple[str, str], Bucket], meta_lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Historic analysis: odds role (favorite / not favorite) × matchup sign vs results",
        "=" * 72,
        *meta_lines,
        "",
    ]
    for role, edge, b in _iter_rows(grid):
        if b.wins + b.losses + b.ties + b.no_result == 0:
            continue
        desc = f"{ODDS_LABEL.get(role, role)}; {EDGE_LABEL.get(edge, edge)}"
        lines.append(desc)
        lines.append(f"  wins: {b.wins}  losses: {b.losses}  ties: {b.ties}  no result: {b.no_result}")
        lines.append(
            f"  decided (W+L only): {b.decided()}  win rate (W / (W+L)): {_rate(b) or 'n/a'}"
        )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _rdylgn_cmap(plt):
    try:
        base = plt.colormaps["RdYlGn"]
    except (AttributeError, KeyError):
        from matplotlib import cm

        base = cm.get_cmap("RdYlGn")
    cmap = base.copy() if hasattr(base, "copy") else base
    cmap.set_bad("#d0d0d0")
    return cmap


def _write_plot(
    path: Path,
    grid: dict[tuple[str, str], Bucket],
    meta_lines: list[str],
) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)

    n_rows = len(ODDS_ORDER_PRIMARY)
    n_cols = len(EDGE_ORDER)
    rates: list[list[float]] = []
    ann: list[list[str]] = []
    for role in ODDS_ORDER_PRIMARY:
        rrow: list[float] = []
        arow: list[str] = []
        for edge in EDGE_ORDER:
            b = grid.get((role, edge)) or Bucket()
            wr = b.win_rate()
            rrow.append(float(wr) if wr is not None else float("nan"))
            arow.append(
                f"{wr:.0%}\nn={b.decided()}" if wr is not None else f"n/a\nn={b.decided()}"
            )
        rates.append(rrow)
        ann.append(arow)

    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    cmap = _rdylgn_cmap(plt)
    im = ax.imshow(
        rates,
        aspect="auto",
        cmap=cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
    )
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(
        [EDGE_LABEL[e] for e in EDGE_ORDER],
        rotation=18,
        ha="right",
    )
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(
        [ODDS_LABEL[r].split(" (")[0] for r in ODDS_ORDER_PRIMARY],
    )
    ax.set_title(
        "Win rate W/(W+L) by moneyline odds vs OBP matchup sign\n"
        "(one row per team-side in historic matchup CSVs)",
        fontsize=11,
    )
    for i in range(n_rows):
        for j in range(n_cols):
            ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=10, color="black")
    plt.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Win rate")
    fig.text(
        0.01,
        0.02,
        "\n".join(meta_lines),
        fontsize=7,
        color="#444444",
        va="bottom",
    )
    fig.subplots_adjust(bottom=0.28, top=0.82, left=0.12, right=0.96)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def run(
    data_dir: Path,
    out_csv: Path,
    out_txt: Path,
    formats: set[str],
    *,
    plot: bool,
    out_png: Path,
) -> None:
    grid, rows_scanned, missing = _collect(data_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "generated_utc": now,
        "data_dir": str(data_dir),
        "matchup_files_rows_scanned": str(rows_scanned),
        "files_skipped_no_results_column": "; ".join(missing) if missing else "(none)",
    }
    meta_lines = [f"{k}: {v}" for k, v in meta.items()]

    if "csv" in formats:
        _write_csv(out_csv, grid)
        print(f"Wrote {out_csv}")
    if "txt" in formats:
        _write_txt(out_txt, grid, meta_lines)
        print(f"Wrote {out_txt}")
    for line in meta_lines:
        print(line)

    if plot:
        try:
            _write_plot(out_png, grid, meta_lines)
            print(f"Wrote {out_png}")
        except ImportError as e:
            print(
                "Skipping PNG (matplotlib not installed). From the project root run:\n"
                "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n"
                "then:\n"
                "  .venv/bin/python analyze_historic_favorites.py\n"
                f"({e})"
            )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument(
        "--out-csv",
        type=Path,
        default=Path("data/results/historic_matchup_odds_results.csv"),
    )
    p.add_argument(
        "--out-txt",
        type=Path,
        default=Path("data/results/historic_matchup_odds_results.txt"),
    )
    p.add_argument(
        "--format",
        choices=("both", "csv", "txt"),
        default="both",
        help="Output format (default: both).",
    )
    p.add_argument(
        "--no-plot",
        dest="plot",
        action="store_false",
        help="Skip PNG heatmap output.",
    )
    p.set_defaults(plot=True)
    p.add_argument(
        "--out-png",
        type=Path,
        default=Path("data/results/historic_matchup_odds_results.png"),
    )
    args = p.parse_args()
    if not args.data_dir.is_dir():
        raise SystemExit(f"data directory not found: {args.data_dir}")

    fmt = {"csv", "txt"} if args.format == "both" else {args.format}
    run(
        args.data_dir,
        args.out_csv,
        args.out_txt,
        fmt,
        plot=args.plot,
        out_png=args.out_png,
    )


if __name__ == "__main__":
    main()
