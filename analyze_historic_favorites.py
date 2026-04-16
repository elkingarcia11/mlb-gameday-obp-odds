"""
Historic matchup CSV analysis: odds, hitting edge, pitching edge vs results.

Reads ``data/YYYY-MM-DD_matchups.csv`` files that include a ``results`` column.
Produces:

- **Marginals** — win rates by ``odds`` alone, ``net_hitting_obp`` sign alone,
  ``net_pitching_obp`` sign alone (when that column exists).
- **Odds × hitting** — sign grid + binned ``net_hitting_obp`` (legacy: ``matchup``).
- **Odds × pitching** — same for ``net_pitching_obp`` when present (negative net
  pitching OBP = lower OBP allowed than opponent = better staff).
- **Hitting × pitching** — 4×4 sign buckets (all moneyline roles combined).
- **Triple** — ``odds`` × hitting sign × pitching sign.

Win rate is **W / (W+L)** only; ties and blank results are counted but excluded
from that denominator.

Default outputs under ``data/results/`` (beside ``historic_matchup_odds_results.*``):

- ``historic_marginals_by_bucket.csv`` — odds, hitting sign, pitching sign alone.
- ``historic_odds_vs_pitching_sign.csv`` / ``.png`` — moneyline × pitching edge sign.
- ``historic_pitching_spread_by_odds.csv`` / ``historic_pitching_spread_winrate.png``
  — binned ``net_pitching_obp`` × favorite / not favorite.
- ``historic_hitting_x_pitching_sign.csv`` / ``.png`` — 4×4 sign cross-tab (all odds).
- ``historic_odds_hitting_pitching_combo.csv`` — full odds × hitting × pitching grid.
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


@dataclass
class Collected:
    grid_odds_hitting: dict[tuple[str, str], Bucket]
    spread_bins_hitting: dict[tuple[str, int], Bucket]
    grid_odds_pitching: dict[tuple[str, str], Bucket]
    spread_bins_pitching: dict[tuple[str, int], Bucket]
    grid_hit_x_pitch: dict[tuple[str, str], Bucket]
    grid_odds_hit_pitch: dict[tuple[str, str, str], Bucket]
    marginal_odds: dict[str, Bucket]
    marginal_hitting: dict[str, Bucket]
    marginal_pitching: dict[str, Bucket]
    rows_in_usable_files: int
    missing_results: list[str]
    has_pitching_column: bool


def _parse_float_col(raw: str) -> float | None:
    try:
        return float((raw or "").strip())
    except ValueError:
        return None


def _row_get_ci(row: dict, name_lc: str) -> str:
    for k, v in row.items():
        if k and k.strip().lower() == name_lc:
            return (v or "").strip()
    return ""


def _spread_hit_from_row(row: dict, field_lc: set[str]) -> float | None:
    if "net_hitting_obp" in field_lc:
        return _parse_float_col(_row_get_ci(row, "net_hitting_obp"))
    return _parse_float_col(_row_get_ci(row, "matchup"))


def _spread_pitch_from_row(row: dict, field_lc: set[str]) -> float | None:
    if "net_pitching_obp" not in field_lc:
        return None
    return _parse_float_col(_row_get_ci(row, "net_pitching_obp"))


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


def _collect(data_dir: Path) -> Collected:
    grid_oh: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    spread_h: dict[tuple[str, int], Bucket] = defaultdict(Bucket)
    grid_op: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    spread_p: dict[tuple[str, int], Bucket] = defaultdict(Bucket)
    grid_hp: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    grid_ohp: dict[tuple[str, str, str], Bucket] = defaultdict(Bucket)
    marg_o: dict[str, Bucket] = defaultdict(Bucket)
    marg_h: dict[str, Bucket] = defaultdict(Bucket)
    marg_p: dict[str, Bucket] = defaultdict(Bucket)
    rows_in_usable_files = 0
    missing_results: list[str] = []
    has_pitching_column = False

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
            field_lc = {h.strip().lower() for h in fields}
            file_has_pitch = "net_pitching_obp" in field_lc
            if file_has_pitch:
                has_pitching_column = True
            for row in reader:
                rows_in_usable_files += 1
                role = _odds_role(row.get("odds", ""))
                nh = _spread_hit_from_row(row, field_lc)
                hit_b = _edge_bucket(nh)
                npv = _spread_pitch_from_row(row, field_lc) if file_has_pitch else None
                pitch_b = _edge_bucket(npv)
                res = _parse_result(row.get("results", ""))

                _add_outcome(marg_o[role], res)
                _add_outcome(marg_h[hit_b], res)
                _add_outcome(grid_oh[(role, hit_b)], res)
                if role in ODDS_ORDER_PRIMARY and nh is not None:
                    _add_outcome(spread_h[(role, _matchup_spread_bin_index(nh))], res)

                if npv is not None:
                    _add_outcome(marg_p[pitch_b], res)
                    _add_outcome(grid_op[(role, pitch_b)], res)
                    if role in ODDS_ORDER_PRIMARY:
                        _add_outcome(
                            spread_p[(role, _matchup_spread_bin_index(npv))], res
                        )
                if nh is not None and npv is not None:
                    _add_outcome(grid_hp[(hit_b, pitch_b)], res)
                    _add_outcome(grid_ohp[(role, hit_b, pitch_b)], res)

    return Collected(
        grid_odds_hitting=dict(grid_oh),
        spread_bins_hitting=dict(spread_h),
        grid_odds_pitching=dict(grid_op),
        spread_bins_pitching=dict(spread_p),
        grid_hit_x_pitch=dict(grid_hp),
        grid_odds_hit_pitch=dict(grid_ohp),
        marginal_odds=dict(marg_o),
        marginal_hitting=dict(marg_h),
        marginal_pitching=dict(marg_p),
        rows_in_usable_files=rows_in_usable_files,
        missing_results=missing_results,
        has_pitching_column=has_pitching_column,
    )


def _rate(b: Bucket) -> str:
    r = b.win_rate()
    return "" if r is None else f"{r:.4f}"


ODDS_LABEL = {
    "favorite": "favorite (moneyline)",
    "not_favorite": "not favorite (moneyline)",
    "other": "other odds label (unknown / equal / …)",
}

EDGE_LABEL = {
    "lt0": "net hitting OBP < 0",
    "eq0": "net hitting OBP = 0",
    "gt0": "net hitting OBP > 0",
    "unknown": "hitting edge unparsable",
}

PITCH_EDGE_LABEL = {
    "lt0": "net pitching OBP < 0 (better staff vs opp)",
    "eq0": "net pitching OBP = 0",
    "gt0": "net pitching OBP > 0 (worse staff vs opp)",
    "unknown": "pitching edge unparsable / missing",
}

EDGE_ORDER = ("lt0", "eq0", "gt0", "unknown")
ODDS_ORDER_ALL = ("favorite", "not_favorite", "other")
ODDS_ORDER_PRIMARY = ("favorite", "not_favorite")

# Ascending hitting-edge (net_hitting_obp / legacy matchup) bin boundaries. Bin i is
# (-inf, b0), [b0,b1), …, [b_{k-1}, +inf) with k = len(_SPREAD_BREAKS) + 1.
_SPREAD_BREAKS = [-0.05, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.05]


def _matchup_spread_bin_index(mu: float) -> int:
    if mu < _SPREAD_BREAKS[0]:
        return 0
    for i in range(1, len(_SPREAD_BREAKS)):
        if mu < _SPREAD_BREAKS[i]:
            return i
    return len(_SPREAD_BREAKS)


def _matchup_spread_bin_bounds(i: int) -> tuple[str, float]:
    """Return (label, x_center_for_plot) for bin index i."""
    k = len(_SPREAD_BREAKS)
    if i == 0:
        lo, hi = float("-inf"), _SPREAD_BREAKS[0]
        label = f"edge < {_SPREAD_BREAKS[0]:.2f}"
        xc = _SPREAD_BREAKS[0] - 0.015
    elif i == k:
        lo, hi = _SPREAD_BREAKS[-1], float("inf")
        label = f"edge ≥ {_SPREAD_BREAKS[-1]:.2f}"
        xc = _SPREAD_BREAKS[-1] + 0.015
    else:
        lo, hi = _SPREAD_BREAKS[i - 1], _SPREAD_BREAKS[i]
        label = f"[{lo:.2f}, {hi:.2f})"
        xc = (lo + hi) / 2
    return label, xc


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


def _write_txt(
    path: Path,
    c: Collected,
    meta_lines: list[str],
    *,
    odds_hit_sign_csv: Path,
    spread_hit_csv: Path,
    spread_hit_png: Path,
    spread_pitch_csv: Path,
    spread_pitch_png: Path,
    marginals_csv: Path,
    combo_csv: Path,
    pitch_sign_csv: Path,
    pitch_sign_png: Path,
    hit_pitch_csv: Path,
    hit_pitch_png: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    grid = c.grid_odds_hitting
    spread_bins = c.spread_bins_hitting
    lines = [
        "Historic analysis — odds, hitting edge, pitching edge (and combinations) vs results",
        "=" * 72,
        *meta_lines,
        "",
        "Output files (CSV / PNG):",
        f"  marginals by bucket: {marginals_csv}",
        f"  odds × hitting sign CSV: {odds_hit_sign_csv}",
        f"  odds × hitting spread bins: {spread_hit_csv}  |  heatmap: {spread_hit_png}",
        f"  odds × pitching sign: {pitch_sign_csv}  |  heatmap: {pitch_sign_png}",
        f"  odds × pitching spread bins: {spread_pitch_csv}  |  heatmap: {spread_pitch_png}",
        f"  hitting × pitching signs (all odds): {hit_pitch_csv}  |  heatmap: {hit_pitch_png}",
        f"  odds × hitting × pitching (full grid): {combo_csv}",
        "",
        "— Odds × hitting edge (sign) —",
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

    n_bins = len(_SPREAD_BREAKS) + 1
    lines.extend(
        [
            "",
            "=" * 72,
            "Hitting edge bins × moneyline (see CSV/PNG paths above)",
            "",
        ]
    )
    for role in ODDS_ORDER_PRIMARY:
        lines.append(ODDS_LABEL.get(role, role))
        for i in range(n_bins):
            b = spread_bins.get((role, i)) or Bucket()
            if b.wins + b.losses + b.ties + b.no_result == 0:
                continue
            label, _xc = _matchup_spread_bin_bounds(i)
            lines.append(f"  {label}")
            lines.append(
                f"    wins: {b.wins}  losses: {b.losses}  ties: {b.ties}  "
                f"decided (W+L): {b.decided()}  win rate: {_rate(b) or 'n/a'}"
            )
        lines.append("")

    if c.has_pitching_column:
        lines.extend(["", "=" * 72, "— Odds × pitching edge (sign) —", ""])
        for role in (*ODDS_ORDER_PRIMARY, "other"):
            for edge in EDGE_ORDER:
                b = c.grid_odds_pitching.get((role, edge)) or Bucket()
                if b.wins + b.losses + b.ties + b.no_result == 0:
                    continue
                desc = f"{ODDS_LABEL.get(role, role)}; {PITCH_EDGE_LABEL.get(edge, edge)}"
                lines.append(desc)
                lines.append(
                    f"  decided: {b.decided()}  win rate: {_rate(b) or 'n/a'}  "
                    f"(W {b.wins} / L {b.losses} / T {b.ties})"
                )
                lines.append("")

        lines.extend(["", "=" * 72, "— Hitting × pitching (non-empty cells) —", ""])
        for he in EDGE_ORDER:
            for pe in EDGE_ORDER:
                b = c.grid_hit_x_pitch.get((he, pe)) or Bucket()
                if b.decided() == 0:
                    continue
                lines.append(
                    f"{EDGE_LABEL.get(he, he)}  ×  {PITCH_EDGE_LABEL.get(pe, pe)}"
                )
                lines.append(f"  decided: {b.decided()}  win rate: {_rate(b) or 'n/a'}")
                lines.append("")
    else:
        lines.extend(
            [
                "",
                "=" * 72,
                "Pitching / combo tables skipped: no net_pitching_obp column in matchup CSVs.",
                "",
            ]
        )

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_spread_csv(path: Path, spread_bins: dict[tuple[str, int], Bucket]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_bins = len(_SPREAD_BREAKS) + 1
    fieldnames = [
        "odds_role",
        "spread_bin_index",
        "spread_bin_label",
        "plot_x_matchup_center",
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
        for role in ODDS_ORDER_PRIMARY:
            for i in range(n_bins):
                b = spread_bins.get((role, i)) or Bucket()
                label, xc = _matchup_spread_bin_bounds(i)
                w.writerow(
                    {
                        "odds_role": role,
                        "spread_bin_index": i,
                        "spread_bin_label": label,
                        "plot_x_matchup_center": f"{xc:.5f}",
                        "wins": b.wins,
                        "losses": b.losses,
                        "ties": b.ties,
                        "no_result": b.no_result,
                        "decided_games": b.decided(),
                        "win_rate_wl_only": _rate(b),
                    }
                )


def _write_odds_pitching_sign_csv(path: Path, grid: dict[tuple[str, str], Bucket]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "odds_role",
        "pitching_edge_bucket",
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
        for role in (*ODDS_ORDER_PRIMARY, "other"):
            for edge in EDGE_ORDER:
                b = grid.get((role, edge)) or Bucket()
                desc = f"{ODDS_LABEL.get(role, role)}; {PITCH_EDGE_LABEL.get(edge, edge)}"
                w.writerow(
                    {
                        "odds_role": role,
                        "pitching_edge_bucket": edge,
                        "description": desc,
                        "wins": b.wins,
                        "losses": b.losses,
                        "ties": b.ties,
                        "no_result": b.no_result,
                        "decided_games": b.decided(),
                        "win_rate_wl_only": _rate(b),
                    }
                )


def _write_pitching_spread_csv(path: Path, spread_bins: dict[tuple[str, int], Bucket]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_bins = len(_SPREAD_BREAKS) + 1
    fieldnames = [
        "odds_role",
        "spread_bin_index",
        "spread_bin_label",
        "plot_x_pitch_edge_center",
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
        for role in ODDS_ORDER_PRIMARY:
            for i in range(n_bins):
                b = spread_bins.get((role, i)) or Bucket()
                label, xc = _matchup_spread_bin_bounds(i)
                w.writerow(
                    {
                        "odds_role": role,
                        "spread_bin_index": i,
                        "spread_bin_label": label,
                        "plot_x_pitch_edge_center": f"{xc:.5f}",
                        "wins": b.wins,
                        "losses": b.losses,
                        "ties": b.ties,
                        "no_result": b.no_result,
                        "decided_games": b.decided(),
                        "win_rate_wl_only": _rate(b),
                    }
                )


def _write_marginals_csv(path: Path, c: Collected) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "dimension",
        "bucket",
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
        for role in ODDS_ORDER_ALL:
            b = c.marginal_odds.get(role) or Bucket()
            w.writerow(
                {
                    "dimension": "odds",
                    "bucket": role,
                    "description": ODDS_LABEL.get(role, role),
                    "wins": b.wins,
                    "losses": b.losses,
                    "ties": b.ties,
                    "no_result": b.no_result,
                    "decided_games": b.decided(),
                    "win_rate_wl_only": _rate(b),
                }
            )
        for edge in EDGE_ORDER:
            b = c.marginal_hitting.get(edge) or Bucket()
            w.writerow(
                {
                    "dimension": "net_hitting_obp_sign",
                    "bucket": edge,
                    "description": EDGE_LABEL.get(edge, edge),
                    "wins": b.wins,
                    "losses": b.losses,
                    "ties": b.ties,
                    "no_result": b.no_result,
                    "decided_games": b.decided(),
                    "win_rate_wl_only": _rate(b),
                }
            )
        if c.has_pitching_column:
            for edge in EDGE_ORDER:
                b = c.marginal_pitching.get(edge) or Bucket()
                w.writerow(
                    {
                        "dimension": "net_pitching_obp_sign",
                        "bucket": edge,
                        "description": PITCH_EDGE_LABEL.get(edge, edge),
                        "wins": b.wins,
                        "losses": b.losses,
                        "ties": b.ties,
                        "no_result": b.no_result,
                        "decided_games": b.decided(),
                        "win_rate_wl_only": _rate(b),
                    }
                )


def _write_combo_csv(path: Path, grid: dict[tuple[str, str, str], Bucket]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "odds_role",
        "hitting_edge_bucket",
        "pitching_edge_bucket",
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
        for role in ODDS_ORDER_ALL:
            for he in EDGE_ORDER:
                for pe in EDGE_ORDER:
                    b = grid.get((role, he, pe)) or Bucket()
                    desc = (
                        f"{ODDS_LABEL.get(role, role)}; "
                        f"{EDGE_LABEL.get(he, he)}; {PITCH_EDGE_LABEL.get(pe, pe)}"
                    )
                    w.writerow(
                        {
                            "odds_role": role,
                            "hitting_edge_bucket": he,
                            "pitching_edge_bucket": pe,
                            "description": desc,
                            "wins": b.wins,
                            "losses": b.losses,
                            "ties": b.ties,
                            "no_result": b.no_result,
                            "decided_games": b.decided(),
                            "win_rate_wl_only": _rate(b),
                        }
                    )


def _write_hit_x_pitch_csv(path: Path, grid: dict[tuple[str, str], Bucket]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "hitting_edge_bucket",
        "pitching_edge_bucket",
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
        for he in EDGE_ORDER:
            for pe in EDGE_ORDER:
                b = grid.get((he, pe)) or Bucket()
                desc = f"{EDGE_LABEL.get(he, he)} × {PITCH_EDGE_LABEL.get(pe, pe)}"
                w.writerow(
                    {
                        "hitting_edge_bucket": he,
                        "pitching_edge_bucket": pe,
                        "description": desc,
                        "wins": b.wins,
                        "losses": b.losses,
                        "ties": b.ties,
                        "no_result": b.no_result,
                        "decided_games": b.decided(),
                        "win_rate_wl_only": _rate(b),
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
        "Win rate W/(W+L) by moneyline odds vs hitting edge sign\n"
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


def _write_spread_plot(
    path: Path,
    spread_bins: dict[tuple[str, int], Bucket],
    meta_lines: list[str],
) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    n_bins = len(_SPREAD_BREAKS) + 1
    n_rows = len(ODDS_ORDER_PRIMARY)
    xlabels: list[str] = []
    for i in range(n_bins):
        lbl, _xc = _matchup_spread_bin_bounds(i)
        xlabels.append(lbl)

    rates: list[list[float]] = []
    ann: list[list[str]] = []
    for role in ODDS_ORDER_PRIMARY:
        rrow: list[float] = []
        arow: list[str] = []
        for i in range(n_bins):
            b = spread_bins.get((role, i)) or Bucket()
            wr = b.win_rate()
            rrow.append(float(wr) if wr is not None else float("nan"))
            arow.append(
                f"{wr:.0%}\nn={b.decided()}" if wr is not None else f"n/a\nn={b.decided()}"
            )
        rates.append(rrow)
        ann.append(arow)

    fig, ax = plt.subplots(figsize=(12.5, 4.6))
    cmap = _rdylgn_cmap(plt)
    im = ax.imshow(
        rates,
        aspect="auto",
        cmap=cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
    )
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(xlabels, rotation=38, ha="right", fontsize=8)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(["Moneyline favorite", "Not favorite"], fontsize=10)
    ax.set_xlabel("Hitting edge bucket (net_hitting_obp = team − opp hitting OBP)")
    ax.set_title(
        "Win rate W/(W+L): hitting-edge buckets × moneyline side\n"
        "Historic team-rows with results (empty-looking cells = n/a or n=0)",
        fontsize=11,
    )
    for i in range(n_rows):
        for j in range(n_bins):
            ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=8, color="black")
    plt.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Win rate")
    fig.text(
        0.01,
        0.01,
        "\n".join(meta_lines),
        fontsize=7,
        color="#444444",
        va="bottom",
    )
    fig.subplots_adjust(bottom=0.34, top=0.84, left=0.09, right=0.97)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _write_odds_pitching_sign_heatmap(
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

    fig, ax = plt.subplots(figsize=(10.0, 4.2))
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
        [PITCH_EDGE_LABEL[e].split(" (")[0] for e in EDGE_ORDER],
        rotation=22,
        ha="right",
        fontsize=9,
    )
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(
        [ODDS_LABEL[r].split(" (")[0] for r in ODDS_ORDER_PRIMARY],
    )
    ax.set_title(
        "Win rate W/(W+L): moneyline vs pitching edge\n"
        "(net pitching OBP = OBP we allow − OBP opp allows; <0 = better staff)",
        fontsize=10,
    )
    for i in range(n_rows):
        for j in range(n_cols):
            ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=9, color="black")
    plt.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Win rate")
    fig.text(0.01, 0.02, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.30, top=0.82, left=0.12, right=0.96)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _write_pitching_spread_heatmap(
    path: Path,
    spread_bins: dict[tuple[str, int], Bucket],
    meta_lines: list[str],
) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    n_bins = len(_SPREAD_BREAKS) + 1
    n_rows = len(ODDS_ORDER_PRIMARY)
    xlabels: list[str] = []
    for i in range(n_bins):
        lbl, _xc = _matchup_spread_bin_bounds(i)
        xlabels.append(lbl)

    rates: list[list[float]] = []
    ann: list[list[str]] = []
    for role in ODDS_ORDER_PRIMARY:
        rrow: list[float] = []
        arow: list[str] = []
        for i in range(n_bins):
            b = spread_bins.get((role, i)) or Bucket()
            wr = b.win_rate()
            rrow.append(float(wr) if wr is not None else float("nan"))
            arow.append(
                f"{wr:.0%}\nn={b.decided()}" if wr is not None else f"n/a\nn={b.decided()}"
            )
        rates.append(rrow)
        ann.append(arow)

    fig, ax = plt.subplots(figsize=(12.5, 4.6))
    cmap = _rdylgn_cmap(plt)
    im = ax.imshow(
        rates,
        aspect="auto",
        cmap=cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
    )
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(xlabels, rotation=38, ha="right", fontsize=8)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(["Moneyline favorite", "Not favorite"], fontsize=10)
    ax.set_xlabel("Pitching edge bucket (net_pitching_obp = our allowed − their allowed)")
    ax.set_title(
        "Win rate W/(W+L): pitching-edge bins × moneyline side\n"
        "Historic rows with pitching column + results",
        fontsize=11,
    )
    for i in range(n_rows):
        for j in range(n_bins):
            ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=8, color="black")
    plt.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="Win rate")
    fig.text(0.01, 0.01, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.34, top=0.84, left=0.09, right=0.97)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _write_hit_x_pitch_heatmap(
    path: Path,
    grid: dict[tuple[str, str], Bucket],
    meta_lines: list[str],
) -> None:
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(EDGE_ORDER)
    hit_short = ("H<0", "H=0", "H>0", "?")
    pit_short = ("P<0", "P=0", "P>0", "?")
    rates: list[list[float]] = []
    ann: list[list[str]] = []
    for hi, he in enumerate(EDGE_ORDER):
        rrow: list[float] = []
        arow: list[str] = []
        for pi, pe in enumerate(EDGE_ORDER):
            b = grid.get((he, pe)) or Bucket()
            wr = b.win_rate()
            rrow.append(float(wr) if wr is not None else float("nan"))
            arow.append(
                f"{wr:.0%}\nn={b.decided()}" if wr is not None else f"n/a\nn={b.decided()}"
            )
        rates.append(rrow)
        ann.append(arow)

    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    cmap = _rdylgn_cmap(plt)
    im = ax.imshow(
        rates,
        aspect="auto",
        cmap=cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
    )
    ax.set_xticks(range(n))
    ax.set_xticklabels(pit_short, fontsize=11)
    ax.set_yticks(range(n))
    ax.set_yticklabels(hit_short, fontsize=11)
    ax.set_xlabel("Pitching edge sign (P<0 = better staff vs opponent)")
    ax.set_ylabel("Hitting edge sign (H>0 = better lineup OBP vs opponent)")
    ax.set_title(
        "Win rate W/(W+L): hitting × pitching sign buckets\n"
        "(all moneyline roles combined; rows with both nets only)",
        fontsize=10,
    )
    for i in range(n):
        for j in range(n):
            ax.text(j, i, ann[i][j], ha="center", va="center", fontsize=9, color="black")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Win rate")
    fig.text(0.02, 0.02, "\n".join(meta_lines), fontsize=7, color="#444444", va="bottom")
    fig.subplots_adjust(bottom=0.18, top=0.88, left=0.14, right=0.94)
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
    out_csv_spread: Path,
    out_png_spread: Path,
) -> None:
    c = _collect(data_dir)
    base = out_csv.parent
    odds_pitch_sign_csv = base / "historic_odds_vs_pitching_sign.csv"
    odds_pitch_sign_png = base / "historic_odds_vs_pitching_sign.png"
    pitch_spread_csv = base / "historic_pitching_spread_by_odds.csv"
    pitch_spread_png = base / "historic_pitching_spread_winrate.png"
    marginals_csv = base / "historic_marginals_by_bucket.csv"
    combo_csv = base / "historic_odds_hitting_pitching_combo.csv"
    hit_pitch_csv = base / "historic_hitting_x_pitching_sign.csv"
    hit_pitch_png = base / "historic_hitting_x_pitching_sign.png"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "generated_utc": now,
        "data_dir": str(data_dir),
        "matchup_files_rows_scanned": str(c.rows_in_usable_files),
        "files_skipped_no_results_column": (
            "; ".join(c.missing_results) if c.missing_results else "(none)"
        ),
        "has_net_pitching_obp_in_any_file": str(c.has_pitching_column),
    }
    meta_lines = [f"{k}: {v}" for k, v in meta.items()]

    if "csv" in formats:
        _write_csv(out_csv, c.grid_odds_hitting)
        print(f"Wrote {out_csv}")
        _write_spread_csv(out_csv_spread, c.spread_bins_hitting)
        print(f"Wrote {out_csv_spread}")
        _write_marginals_csv(marginals_csv, c)
        print(f"Wrote {marginals_csv}")
        if c.has_pitching_column:
            _write_odds_pitching_sign_csv(odds_pitch_sign_csv, c.grid_odds_pitching)
            print(f"Wrote {odds_pitch_sign_csv}")
            _write_pitching_spread_csv(pitch_spread_csv, c.spread_bins_pitching)
            print(f"Wrote {pitch_spread_csv}")
            _write_combo_csv(combo_csv, c.grid_odds_hit_pitch)
            print(f"Wrote {combo_csv}")
            _write_hit_x_pitch_csv(hit_pitch_csv, c.grid_hit_x_pitch)
            print(f"Wrote {hit_pitch_csv}")
    if "txt" in formats:
        _write_txt(
            out_txt,
            c,
            meta_lines,
            odds_hit_sign_csv=out_csv,
            spread_hit_csv=out_csv_spread,
            spread_hit_png=out_png_spread,
            spread_pitch_csv=pitch_spread_csv,
            spread_pitch_png=pitch_spread_png,
            marginals_csv=marginals_csv,
            combo_csv=combo_csv,
            pitch_sign_csv=odds_pitch_sign_csv,
            pitch_sign_png=odds_pitch_sign_png,
            hit_pitch_csv=hit_pitch_csv,
            hit_pitch_png=hit_pitch_png,
        )
        print(f"Wrote {out_txt}")
    for line in meta_lines:
        print(line)
    print(f"Binned hitting spread: {out_csv_spread}")
    print(f"Binned hitting spread PNG: {out_png_spread}")

    if plot:
        try:
            _write_plot(out_png, c.grid_odds_hitting, meta_lines)
            print(f"Wrote {out_png}")
            _write_spread_plot(out_png_spread, c.spread_bins_hitting, meta_lines)
            print(f"Wrote {out_png_spread}")
            if c.has_pitching_column:
                _write_odds_pitching_sign_heatmap(
                    odds_pitch_sign_png, c.grid_odds_pitching, meta_lines
                )
                print(f"Wrote {odds_pitch_sign_png}")
                _write_pitching_spread_heatmap(
                    pitch_spread_png, c.spread_bins_pitching, meta_lines
                )
                print(f"Wrote {pitch_spread_png}")
                _write_hit_x_pitch_heatmap(hit_pitch_png, c.grid_hit_x_pitch, meta_lines)
                print(f"Wrote {hit_pitch_png}")
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
    p.add_argument(
        "--out-csv-spread",
        type=Path,
        default=Path("data/results/historic_matchup_spread_by_odds.csv"),
    )
    p.add_argument(
        "--out-png-spread",
        type=Path,
        default=Path("data/results/historic_matchup_spread_winrate.png"),
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
        out_csv_spread=args.out_csv_spread,
        out_png_spread=args.out_png_spread,
    )


if __name__ == "__main__":
    main()
