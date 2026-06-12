"""
Betting analytics from historic matchup CSVs with moneylines and results.

Only rows with a decided result (W/L), parsable ``net_hitting_obp`` (or legacy
``matchup``), and a numeric ``moneyline`` are included. Everything else is
skipped for these charts.

Outputs under ``data/results/`` (CSV + PNG when matplotlib is available):

- Net OBP edge vs win rate
- Net OBP edge vs ROI (flat $100 bets)
- Heatmap: net OBP edge × moneyline bucket → ROI
- Actual vs implied win probability (by net OBP threshold)
- Scatter: net OBP edge vs closing moneyline (one point per team-side)
- Calibration: OBP-based expected win % vs actual win % by edge bucket
- Team × net OBP edge heatmap (ROI)
- Value score tiers (net OBP edge − implied probability)
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from analyze_historic_favorites import (
    _SPREAD_BREAKS,
    _matchup_spread_bin_bounds,
    _matchup_spread_bin_index,
    _parse_result,
    _row_get_ci,
    _spread_hit_from_row,
)

# Moneyline column order for heatmaps (underdog → favorite).
_ML_BUCKET_BOUNDS: list[tuple[int | None, int | None, str]] = [
    (150, None, "+150+"),
    (100, 149, "+100 to +149"),
    (-149, -100, "-100 to -149"),
    (None, -150, "-150+"),
]

_FLAT_STAKE = 100.0
# Simple OBP-edge expectation for calibration (not a fitted model).
_CALIB_SLOPE = 4.0

# Net OBP thresholds for actual-vs-implied table.
_OBP_THRESHOLDS = (0.015, 0.025, 0.035)


@dataclass
class BetRow:
    game_pk: str
    team: str
    net_obp: float
    moneyline: int
    result: str
    implied_prob: float
    profit: float


@dataclass
class RoiBucket:
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    risked: float = 0.0

    def decided(self) -> int:
        return self.wins + self.losses

    def win_rate(self) -> float | None:
        d = self.decided()
        if d == 0:
            return None
        return self.wins / d

    def roi(self) -> float | None:
        if self.risked == 0:
            return None
        return self.profit / self.risked

    def add(self, row: BetRow) -> None:
        self.risked += _FLAT_STAKE
        self.profit += row.profit
        if row.result == "W":
            self.wins += 1
        else:
            self.losses += 1


@dataclass
class BettingCollected:
    rows: list[BetRow] = field(default_factory=list)
    skipped_no_result: int = 0
    skipped_no_obp: int = 0
    skipped_no_moneyline: int = 0
    files_scanned: int = 0


def _parse_moneyline(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return int(s.replace("+", ""))
    except ValueError:
        return None


def implied_prob_american(ml: int) -> float:
    if ml < 0:
        return abs(ml) / (abs(ml) + 100.0)
    return 100.0 / (ml + 100.0)


def profit_flat_bet(ml: int, won: bool) -> float:
    if not won:
        return -_FLAT_STAKE
    if ml > 0:
        return float(ml)
    return _FLAT_STAKE * (100.0 / abs(ml))


def _moneyline_bin_index(ml: int) -> int | None:
    for i, (lo, hi, _label) in enumerate(_ML_BUCKET_BOUNDS):
        if lo is not None and ml < lo:
            continue
        if hi is not None and ml > hi:
            continue
        return i
    return None


def _moneyline_bin_label(i: int) -> str:
    return _ML_BUCKET_BOUNDS[i][2]


def _obp_bin_midpoint(i: int) -> float:
    k = len(_SPREAD_BREAKS)
    if i == 0:
        return _SPREAD_BREAKS[0] - 0.01
    if i == k:
        return _SPREAD_BREAKS[-1] + 0.01
    lo, hi = _SPREAD_BREAKS[i - 1], _SPREAD_BREAKS[i]
    return (lo + hi) / 2.0


def expected_win_from_obp(net_obp: float) -> float:
    return min(0.95, max(0.05, 0.50 + net_obp * _CALIB_SLOPE))


def _collect_bet_rows(data_dir: Path) -> BettingCollected:
    out = BettingCollected()
    for path in sorted(data_dir.glob("*_matchups.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            if not fields:
                continue
            if not any(h.strip().lower() == "results" for h in fields):
                continue
            field_lc = {h.strip().lower() for h in fields}
            if "moneyline" not in field_lc:
                continue
            out.files_scanned += 1
            for row in reader:
                res = _parse_result(row.get("results", ""))
                if res not in {"W", "L"}:
                    out.skipped_no_result += 1
                    continue
                net = _spread_hit_from_row(row, field_lc)
                if net is None:
                    out.skipped_no_obp += 1
                    continue
                ml = _parse_moneyline(_row_get_ci(row, "moneyline"))
                if ml is None:
                    out.skipped_no_moneyline += 1
                    continue
                imp = implied_prob_american(ml)
                profit = profit_flat_bet(ml, res == "W")
                out.rows.append(
                    BetRow(
                        game_pk=(row.get("game_pk") or "").strip(),
                        team=(row.get("team") or "").strip(),
                        net_obp=net,
                        moneyline=ml,
                        result=res,
                        implied_prob=imp,
                        profit=profit,
                    )
                )
    return out


def _meta_lines(c: BettingCollected, data_dir: Path) -> list[str]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        f"generated_utc: {now}",
        f"data_dir: {data_dir}",
        f"usable_bet_rows: {len(c.rows)}",
        f"files_with_moneyline_and_results: {c.files_scanned}",
        f"skipped_no_wl_result: {c.skipped_no_result}",
        f"skipped_no_net_obp: {c.skipped_no_obp}",
        f"skipped_no_moneyline: {c.skipped_no_moneyline}",
        f"flat_stake_usd: {_FLAT_STAKE}",
    ]


def _aggregate_obp_buckets(rows: list[BetRow]) -> dict[int, RoiBucket]:
    buckets: dict[int, RoiBucket] = {}
    for row in rows:
        i = _matchup_spread_bin_index(row.net_obp)
        buckets.setdefault(i, RoiBucket()).add(row)
    return buckets


def _write_net_obp_winrate_csv(path: Path, buckets: dict[int, RoiBucket]) -> None:
    n_bins = len(_SPREAD_BREAKS) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "net_obp_bucket",
                "wins",
                "losses",
                "decided_games",
                "win_rate",
            ],
        )
        w.writeheader()
        for i in range(n_bins):
            b = buckets.get(i) or RoiBucket()
            label, _ = _matchup_spread_bin_bounds(i)
            wr = b.win_rate()
            w.writerow(
                {
                    "net_obp_bucket": label,
                    "wins": b.wins,
                    "losses": b.losses,
                    "decided_games": b.decided(),
                    "win_rate": "" if wr is None else f"{wr:.4f}",
                }
            )


def _write_net_obp_roi_csv(path: Path, buckets: dict[int, RoiBucket]) -> None:
    n_bins = len(_SPREAD_BREAKS) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "net_obp_bucket",
                "wins",
                "losses",
                "total_risked",
                "total_profit",
                "roi",
            ],
        )
        w.writeheader()
        for i in range(n_bins):
            b = buckets.get(i) or RoiBucket()
            label, _ = _matchup_spread_bin_bounds(i)
            roi = b.roi()
            w.writerow(
                {
                    "net_obp_bucket": label,
                    "wins": b.wins,
                    "losses": b.losses,
                    "total_risked": f"{b.risked:.2f}",
                    "total_profit": f"{b.profit:.2f}",
                    "roi": "" if roi is None else f"{roi:.4f}",
                }
            )


def _aggregate_obp_ml_grid(rows: list[BetRow]) -> dict[tuple[int, int], RoiBucket]:
    grid: dict[tuple[int, int], RoiBucket] = {}
    for row in rows:
        obp_i = _matchup_spread_bin_index(row.net_obp)
        ml_i = _moneyline_bin_index(row.moneyline)
        if ml_i is None:
            continue
        grid.setdefault((obp_i, ml_i), RoiBucket()).add(row)
    return grid


def _write_obp_ml_heatmap_csv(
    path: Path, grid: dict[tuple[int, int], RoiBucket]
) -> None:
    n_obp = len(_SPREAD_BREAKS) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "net_obp_bucket",
                "moneyline_bucket",
                "wins",
                "losses",
                "decided_games",
                "roi",
            ],
        )
        w.writeheader()
        for obp_i in range(n_obp):
            label_obp, _ = _matchup_spread_bin_bounds(obp_i)
            for ml_i in range(len(_ML_BUCKET_BOUNDS)):
                b = grid.get((obp_i, ml_i)) or RoiBucket()
                roi = b.roi()
                w.writerow(
                    {
                        "net_obp_bucket": label_obp,
                        "moneyline_bucket": _moneyline_bin_label(ml_i),
                        "wins": b.wins,
                        "losses": b.losses,
                        "decided_games": b.decided(),
                        "roi": "" if roi is None else f"{roi:.4f}",
                    }
                )


def _write_actual_vs_implied_csv(path: Path, rows: list[BetRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "bucket",
                "games",
                "actual_win_rate",
                "avg_implied_prob",
                "edge_actual_minus_implied",
            ],
        )
        w.writeheader()
        for thr in _OBP_THRESHOLDS:
            subset = [r for r in rows if r.net_obp > thr]
            if not subset:
                w.writerow(
                    {
                        "bucket": f"net_obp > {thr:.3f}",
                        "games": 0,
                        "actual_win_rate": "",
                        "avg_implied_prob": "",
                        "edge_actual_minus_implied": "",
                    }
                )
                continue
            wins = sum(1 for r in subset if r.result == "W")
            actual = wins / len(subset)
            avg_imp = sum(r.implied_prob for r in subset) / len(subset)
            w.writerow(
                {
                    "bucket": f"net_obp > {thr:.3f}",
                    "games": len(subset),
                    "actual_win_rate": f"{actual:.4f}",
                    "avg_implied_prob": f"{avg_imp:.4f}",
                    "edge_actual_minus_implied": f"{actual - avg_imp:.4f}",
                }
            )


def _write_calibration_csv(path: Path, buckets: dict[int, RoiBucket]) -> None:
    n_bins = len(_SPREAD_BREAKS) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "net_obp_bucket",
                "expected_win_rate_obp_model",
                "actual_win_rate",
                "games",
            ],
        )
        w.writeheader()
        for i in range(n_bins):
            b = buckets.get(i) or RoiBucket()
            label, _ = _matchup_spread_bin_bounds(i)
            mid = _obp_bin_midpoint(i)
            expected = expected_win_from_obp(mid)
            actual = b.win_rate()
            w.writerow(
                {
                    "net_obp_bucket": label,
                    "expected_win_rate_obp_model": f"{expected:.4f}",
                    "actual_win_rate": "" if actual is None else f"{actual:.4f}",
                    "games": b.decided(),
                }
            )


def _aggregate_team_obp(rows: list[BetRow]) -> dict[tuple[str, int], RoiBucket]:
    grid: dict[tuple[str, int], RoiBucket] = {}
    for row in rows:
        if not row.team:
            continue
        obp_i = _matchup_spread_bin_index(row.net_obp)
        grid.setdefault((row.team, obp_i), RoiBucket()).add(row)
    return grid


def _write_team_obp_csv(path: Path, grid: dict[tuple[str, int], RoiBucket]) -> None:
    n_bins = len(_SPREAD_BREAKS) + 1
    teams = sorted({t for t, _ in grid})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "team",
                "net_obp_bucket",
                "wins",
                "losses",
                "decided_games",
                "roi",
            ],
        )
        w.writeheader()
        for team in teams:
            for i in range(n_bins):
                b = grid.get((team, i)) or RoiBucket()
                if b.decided() == 0:
                    continue
                label, _ = _matchup_spread_bin_bounds(i)
                roi = b.roi()
                w.writerow(
                    {
                        "team": team,
                        "net_obp_bucket": label,
                        "wins": b.wins,
                        "losses": b.losses,
                        "decided_games": b.decided(),
                        "roi": "" if roi is None else f"{roi:.4f}",
                    }
                )


def _write_value_score_csv(path: Path, rows: list[BetRow]) -> None:
    if not rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "tier,games,wins,losses,win_rate,total_risked,total_profit,roi\n",
            encoding="utf-8",
        )
        return
    scored = sorted(rows, key=lambda r: (r.net_obp - r.implied_prob), reverse=True)
    n = len(scored)
    tiers = [
        ("top_10pct", int(n * 0.10) or 1),
        ("top_20pct", int(n * 0.20) or 1),
        ("top_30pct", int(n * 0.30) or 1),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "tier",
                "games",
                "wins",
                "losses",
                "win_rate",
                "total_risked",
                "total_profit",
                "roi",
            ],
        )
        w.writeheader()
        for name, k in tiers:
            subset = scored[:k]
            b = RoiBucket()
            for row in subset:
                b.add(row)
            wr = b.win_rate()
            roi = b.roi()
            w.writerow(
                {
                    "tier": name,
                    "games": b.decided(),
                    "wins": b.wins,
                    "losses": b.losses,
                    "win_rate": "" if wr is None else f"{wr:.4f}",
                    "total_risked": f"{b.risked:.2f}",
                    "total_profit": f"{b.profit:.2f}",
                    "roi": "" if roi is None else f"{roi:.4f}",
                }
            )


def _rdylgn_cmap(plt):
    try:
        base = plt.colormaps["RdYlGn"]
    except (AttributeError, KeyError):
        from matplotlib import cm

        base = cm.get_cmap("RdYlGn")
    cmap = base.copy() if hasattr(base, "copy") else base
    cmap.set_bad("#d0d0d0")
    return cmap


def _plot_net_obp_winrate(
    path: Path, buckets: dict[int, RoiBucket], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    n_bins = len(_SPREAD_BREAKS) + 1
    labels = []
    rates = []
    counts = []
    for i in range(n_bins):
        b = buckets.get(i) or RoiBucket()
        label, _ = _matchup_spread_bin_bounds(i)
        labels.append(label)
        wr = b.win_rate()
        rates.append(wr if wr is not None else float("nan"))
        counts.append(b.decided())

    fig, ax = plt.subplots(figsize=(12, 5))
    x = range(n_bins)
    ax.bar(x, [r * 100 if r == r else 0 for r in rates], color="#4c78a8")
    ax.axhline(50, color="#888888", linestyle="--", linewidth=1)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Win %")
    ax.set_xlabel("Net OBP edge bucket")
    ax.set_title("Net OBP edge vs win rate (W / (W+L), flat team-sides)")
    for i, (r, n) in enumerate(zip(rates, counts)):
        if n and r == r:
            ax.text(i, r * 100 + 1, f"n={n}", ha="center", fontsize=7)
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_net_obp_roi(
    path: Path, buckets: dict[int, RoiBucket], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    n_bins = len(_SPREAD_BREAKS) + 1
    labels = []
    rois = []
    counts = []
    for i in range(n_bins):
        b = buckets.get(i) or RoiBucket()
        label, _ = _matchup_spread_bin_bounds(i)
        labels.append(label)
        roi = b.roi()
        rois.append(roi * 100 if roi is not None else float("nan"))
        counts.append(b.decided())

    fig, ax = plt.subplots(figsize=(12, 5))
    x = range(n_bins)
    colors = ["#54a24b" if (r == r and r >= 0) else "#e45756" for r in rois]
    ax.bar(x, rois, color=colors)
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("ROI %")
    ax.set_xlabel("Net OBP edge bucket")
    ax.set_title(f"Net OBP edge vs ROI (flat ${_FLAT_STAKE:.0f} bets)")
    for i, (r, n) in enumerate(zip(rois, counts)):
        if n and r == r:
            ax.text(i, r + (2 if r >= 0 else -4), f"n={n}", ha="center", fontsize=7)
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_obp_ml_heatmap(
    path: Path, grid: dict[tuple[int, int], RoiBucket], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    n_obp = len(_SPREAD_BREAKS) + 1
    n_ml = len(_ML_BUCKET_BOUNDS)
    rates: list[list[float]] = []
    ann: list[list[str]] = []
    ylabels = []
    for obp_i in range(n_obp - 1, -1, -1):
        label, _ = _matchup_spread_bin_bounds(obp_i)
        ylabels.append(label)
        rrow: list[float] = []
        arow: list[str] = []
        for ml_i in range(n_ml):
            b = grid.get((obp_i, ml_i)) or RoiBucket()
            roi = b.roi()
            rrow.append(roi * 100 if roi is not None else float("nan"))
            arow.append(
                f"{roi:.0%}\nn={b.decided()}" if roi is not None else f"n/a\nn={b.decided()}"
            )
        rates.append(rrow)
        ann.append(arow)

    fig, ax = plt.subplots(figsize=(10, 8))
    cmap = _rdylgn_cmap(plt)
    vmax = 25.0
    vmin = -25.0
    im = ax.imshow(
        rates,
        aspect="auto",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
    )
    ax.set_xticks(range(n_ml))
    ax.set_xticklabels([_moneyline_bin_label(i) for i in range(n_ml)], rotation=25, ha="right")
    ax.set_yticks(range(n_obp))
    ax.set_yticklabels(ylabels, fontsize=8)
    ax.set_xlabel("Moneyline bucket (closing)")
    ax.set_ylabel("Net OBP edge bucket")
    ax.set_title("ROI % heatmap: net OBP edge × moneyline")
    for i in range(n_obp):
        for j in range(n_ml):
            ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=7, color="black")
    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="ROI %")
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.22, left=0.22)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_actual_vs_implied(
    path: Path, rows: list[BetRow], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    labels = []
    actuals = []
    implieds = []
    for thr in _OBP_THRESHOLDS:
        subset = [r for r in rows if r.net_obp > thr]
        labels.append(f">{thr:.3f}")
        if not subset:
            actuals.append(float("nan"))
            implieds.append(float("nan"))
            continue
        wins = sum(1 for r in subset if r.result == "W")
        actuals.append(wins / len(subset) * 100)
        implieds.append(sum(r.implied_prob for r in subset) / len(subset) * 100)

    x = range(len(labels))
    w = 0.35
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([i - w / 2 for i in x], actuals, width=w, label="Actual win %", color="#4c78a8")
    ax.bar([i + w / 2 for i in x], implieds, width=w, label="Avg implied %", color="#f58518")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Win %")
    ax.set_xlabel("Net OBP edge threshold")
    ax.set_title("Actual vs implied win probability")
    ax.legend()
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_scatter(path: Path, rows: list[BetRow], meta_lines: list[str]) -> None:
    import matplotlib.pyplot as plt

    xs = [r.net_obp for r in rows]
    ys = [r.moneyline for r in rows]
    colors = ["#54a24b" if r.result == "W" else "#e45756" for r in rows]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(xs, ys, c=colors, alpha=0.55, s=28, edgecolors="none")
    ax.axvline(0, color="#aaaaaa", linewidth=0.8)
    ax.axhline(0, color="#aaaaaa", linewidth=0.8)
    ax.set_xlabel("Net OBP edge")
    ax.set_ylabel("Closing moneyline (American)")
    ax.set_title("Net OBP edge vs closing odds (green=W, red=L)")
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_calibration(
    path: Path, buckets: dict[int, RoiBucket], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    n_bins = len(_SPREAD_BREAKS) + 1
    labels = []
    expected = []
    actual = []
    for i in range(n_bins):
        b = buckets.get(i) or RoiBucket()
        if b.decided() == 0:
            continue
        label, _ = _matchup_spread_bin_bounds(i)
        labels.append(label)
        mid = _obp_bin_midpoint(i)
        expected.append(expected_win_from_obp(mid) * 100)
        wr = b.win_rate()
        actual.append(wr * 100 if wr is not None else float("nan"))

    if not labels:
        return

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(x, expected, marker="o", label="Expected (OBP model)", color="#f58518")
    ax.plot(x, actual, marker="s", label="Actual win %", color="#4c78a8")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Win %")
    ax.set_xlabel("Net OBP edge bucket")
    ax.set_title("Calibration: OBP-based expected vs actual win rate")
    ax.legend()
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_team_heatmap(
    path: Path, grid: dict[tuple[str, int], RoiBucket], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    n_bins = len(_SPREAD_BREAKS) + 1
    teams = sorted({t for t, _ in grid})
    if not teams:
        return
    xlabels = [_matchup_spread_bin_bounds(i)[0] for i in range(n_bins)]
    rates: list[list[float]] = []
    ann: list[list[str]] = []
    for team in teams:
        rrow: list[float] = []
        arow: list[str] = []
        for i in range(n_bins):
            b = grid.get((team, i)) or RoiBucket()
            roi = b.roi()
            rrow.append(roi * 100 if roi is not None else float("nan"))
            arow.append(
                f"{roi:.0%}\nn={b.decided()}" if roi is not None else ""
            )
        rates.append(rrow)
        ann.append(arow)

    fig_h = max(6, len(teams) * 0.28)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    cmap = _rdylgn_cmap(plt)
    im = ax.imshow(
        rates,
        aspect="auto",
        cmap=cmap,
        vmin=-30,
        vmax=30,
        interpolation="nearest",
    )
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(xlabels, rotation=50, ha="right", fontsize=7)
    ax.set_yticks(range(len(teams)))
    ax.set_yticklabels(teams, fontsize=8)
    ax.set_title("Team ROI % by net OBP edge bucket")
    for i in range(len(teams)):
        for j in range(n_bins):
            if ann[i][j]:
                ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=6, color="black")
    plt.colorbar(im, ax=ax, fraction=0.02, pad=0.02, label="ROI %")
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.28, left=0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_value_score(
    path: Path, rows: list[BetRow], meta_lines: list[str]
) -> None:
    import matplotlib.pyplot as plt

    if not rows:
        return
    scored = sorted(rows, key=lambda r: (r.net_obp - r.implied_prob), reverse=True)
    n = len(scored)
    tiers = [
        ("Top 10%", int(n * 0.10) or 1),
        ("Top 20%", int(n * 0.20) or 1),
        ("Top 30%", int(n * 0.30) or 1),
    ]
    labels = []
    rois = []
    for label, k in tiers:
        subset = scored[:k]
        b = RoiBucket()
        for row in subset:
            b.add(row)
        roi = b.roi()
        labels.append(label)
        rois.append(roi * 100 if roi is not None else float("nan"))

    fig, ax = plt.subplots(figsize=(7, 5))
    colors = ["#54a24b" if (r == r and r >= 0) else "#e45756" for r in rois]
    ax.bar(labels, rois, color=colors)
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_ylabel("ROI %")
    ax.set_title("Value score tiers (net OBP edge − implied probability)")
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _write_summary_txt(path: Path, meta_lines: list[str], outputs: list[str]) -> None:
    lines = [
        "Betting analytics (moneyline + net OBP + results required per row)",
        "=" * 72,
        *meta_lines,
        "",
        "Outputs:",
        *[f"  {p}" for p in outputs],
        "",
        "Rows without W/L, net OBP, or moneyline are excluded from all charts.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(data_dir: Path, results_dir: Path, *, plot: bool = True) -> BettingCollected:
    c = _collect_bet_rows(data_dir)
    meta = _meta_lines(c, data_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    obp_buckets = _aggregate_obp_buckets(c.rows)
    obp_ml_grid = _aggregate_obp_ml_grid(c.rows)
    team_grid = _aggregate_team_obp(c.rows)

    paths = {
        "winrate_csv": results_dir / "historic_net_obp_vs_winrate.csv",
        "winrate_png": results_dir / "historic_net_obp_vs_winrate.png",
        "roi_csv": results_dir / "historic_net_obp_vs_roi.csv",
        "roi_png": results_dir / "historic_net_obp_vs_roi.png",
        "heatmap_csv": results_dir / "historic_net_obp_x_moneyline_roi.csv",
        "heatmap_png": results_dir / "historic_net_obp_x_moneyline_roi.png",
        "implied_csv": results_dir / "historic_actual_vs_implied.csv",
        "implied_png": results_dir / "historic_actual_vs_implied.png",
        "scatter_png": results_dir / "historic_net_obp_vs_moneyline_scatter.png",
        "calibration_csv": results_dir / "historic_calibration_curve.csv",
        "calibration_png": results_dir / "historic_calibration_curve.png",
        "team_csv": results_dir / "historic_team_net_obp_roi.csv",
        "team_png": results_dir / "historic_team_net_obp_roi.png",
        "value_csv": results_dir / "historic_value_score_roi.csv",
        "value_png": results_dir / "historic_value_score_roi.png",
        "summary_txt": results_dir / "historic_betting_charts.txt",
    }

    _write_net_obp_winrate_csv(paths["winrate_csv"], obp_buckets)
    _write_net_obp_roi_csv(paths["roi_csv"], obp_buckets)
    _write_obp_ml_heatmap_csv(paths["heatmap_csv"], obp_ml_grid)
    _write_actual_vs_implied_csv(paths["implied_csv"], c.rows)
    _write_calibration_csv(paths["calibration_csv"], obp_buckets)
    _write_team_obp_csv(paths["team_csv"], team_grid)
    _write_value_score_csv(paths["value_csv"], c.rows)

    for key in (
        "winrate_csv",
        "roi_csv",
        "heatmap_csv",
        "implied_csv",
        "calibration_csv",
        "team_csv",
        "value_csv",
    ):
        print(f"Wrote {paths[key]}")

    out_list = [str(paths[k]) for k in paths if k.endswith("_csv") or k == "summary_txt"]
    _write_summary_txt(paths["summary_txt"], meta, out_list)
    print(f"Wrote {paths['summary_txt']}")

    for line in meta:
        print(line)

    if not c.rows:
        print(
            "No usable bet rows (need results + moneyline + net_hitting_obp). "
            "Skipping PNG charts."
        )
        return c

    if plot:
        try:
            _plot_net_obp_winrate(paths["winrate_png"], obp_buckets, meta)
            _plot_net_obp_roi(paths["roi_png"], obp_buckets, meta)
            _plot_obp_ml_heatmap(paths["heatmap_png"], obp_ml_grid, meta)
            _plot_actual_vs_implied(paths["implied_png"], c.rows, meta)
            _plot_scatter(paths["scatter_png"], c.rows, meta)
            _plot_calibration(paths["calibration_png"], obp_buckets, meta)
            _plot_team_heatmap(paths["team_png"], team_grid, meta)
            _plot_value_score(paths["value_png"], c.rows, meta)
            for key in (
                "winrate_png",
                "roi_png",
                "heatmap_png",
                "implied_png",
                "scatter_png",
                "calibration_png",
                "team_png",
                "value_png",
            ):
                print(f"Wrote {paths[key]}")
        except ImportError as e:
            print(
                "Skipping betting PNGs (matplotlib not installed). "
                f"({e})"
            )

    return c


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument(
        "--results-dir",
        type=Path,
        default=Path("data/results"),
    )
    p.add_argument("--no-plot", dest="plot", action="store_false")
    p.set_defaults(plot=True)
    args = p.parse_args()
    if not args.data_dir.is_dir():
        raise SystemExit(f"data directory not found: {args.data_dir}")
    run(args.data_dir, args.results_dir, plot=args.plot)


if __name__ == "__main__":
    main()
