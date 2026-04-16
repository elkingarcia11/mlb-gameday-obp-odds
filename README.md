# MLB gameday — hitting & pitching OBP vs moneylines

**Repository:** `mlb-gameday-obp-odds` (local folder / GitHub repo name)

A small Python tool that pulls **MLB Stats API** team rates and **today’s** schedule, **ESPN** moneylines for the slate, and writes **matchup CSVs** with **hitting edge**, **pitching edge** (OBP allowed), and **favorite / not favorite** labels. Past slates can be **backfilled** with **W / L / T**, then **historic analysis** summarizes how those edges and odds line up with **results**.

Running **`main.py`** backfills finished games into older `*_matchups.csv` rows (`results`), rebuilds **historic analysis** under **`data/results/`**, then writes **today’s** team and matchup files.

## What it does

### Daily pipeline (`main.py`)

1. **Backfill results** — Scans `data/*_matchups.csv` for dates **before today**. If a file has no `results` column yet, the script loads that day’s schedule from the **MLB Stats API**, maps each row’s `game_pk` and `team` to **W**, **L**, or **T**, and rewrites the CSV with a trailing **`results`** column. Files that already include `results`, and **today’s** matchup file, are skipped.
2. **Historic analysis** — Recomputes summaries under **`data/results/`**: moneyline role vs **hitting** edge (sign + binned `net_hitting_obp`), and—when matchup files include **`net_pitching_obp`**—**marginals**, **odds × pitching**, **binned pitching spread**, **hitting × pitching** sign cross-tabs, and an **odds × hitting × pitching** combo grid (CSV; optional PNGs need **matplotlib**, see [Requirements](#requirements)).
3. **Today’s snapshot** — Team rate CSV (`hitting_obp`, `pitching_obp`) and today’s matchup CSV (no `results` yet for the live slate).

### Stats and matchup columns

**MLB Stats API** (`https://statsapi.mlb.com/api/v1`):

- **`group=hitting`** — each team’s season **batting** OBP (same idea as [mlb.com team hitting OBP](https://www.mlb.com/stats/team/on-base-percentage)).
- **`group=pitching`** — each team’s **`obp`** is **OBP allowed to all opposing hitters** that season (staff/defense line, not the lineup’s OBP).

**`data/YYYY-MM-DD.csv`** (one row per team):

| Column         | Meaning |
| -------------- | ------- |
| `team_id`      | MLB club id |
| `team_name`    | Club name |
| `hitting_obp`  | Season batting OBP |
| `pitching_obp` | Season OBP **allowed** (pitching group stat) |

**`data/YYYY-MM-DD_matchups.csv`** (two rows per scheduled game — away and home team-sides; cancelled/postponed games omitted):

| Column                     | Meaning |
| -------------------------- | ------- |
| `game_pk`                  | MLB game id |
| `team` / `opponent`        | This row’s club and opponent |
| `hitting_obp`              | This team’s season batting OBP |
| `opponent_hitting_obp`     | Opponent’s season batting OBP |
| `pitching_obp`             | This team’s season OBP **allowed** |
| `opponent_pitching_obp`    | Opponent’s season OBP **allowed** |
| `net_hitting_obp`          | `hitting_obp − opponent_hitting_obp` (**higher** = better lineup edge) |
| `net_pitching_obp`         | `pitching_obp − opponent_pitching_obp` (**lower / more negative** = you allow less OBP than they do = better staff edge) |
| `odds`                     | `favorite` / `not favorite` / `equal` / `unknown` (see below) |
| `results`                  | After backfill on past dates: `W` / `L` / `T` or blank |

Rows are sorted by **`net_hitting_obp` descending**, then **`net_pitching_obp` ascending** (stronger hitting edge first; for ties, lean toward the better relative pitching number).

**Betting `odds`** — ESPN scoreboard + per-game **summary** `pickcenter` (often **DraftKings**). American moneylines: **`favorite`** if this team’s line is **less than** the opponent’s (e.g. `-150` vs `+130`), **`not favorite`** if greater, **`equal`** if tied, **`unknown`** if missing or the game could not be matched by team names.

Older matchup CSVs may still use legacy columns (`obp`, `opponent_obp`, `matchup`). Historic analysis prefers **`net_hitting_obp`** when present, else **`matchup`**, for hitting-edge charts.

## Requirements

- **Python 3.10+** for `main.py`, `backfill_matchup_results.py`, and the analysis script (stdlib + `urllib`).
- **Optional (PNGs):** **matplotlib** in `requirements.txt`. On macOS/Homebrew Python (**PEP 668**), use a venv:

  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python main.py
  ```

The repository **`.gitignore`** ignores `.venv/`.

## How to run

### Full daily run (recommended)

```bash
.venv/bin/python main.py
```

or `python3 main.py` (PNGs skipped if matplotlib is missing).

The script uses **today’s date** on your machine for the schedule, season year, and output filenames.

### Standalone utilities

| Script | Purpose |
| ------ | ------- |
| `backfill_matchup_results.py` | Backfill `results` only on past `data/YYYY-MM-DD_matchups.csv` (same rules as step 1). `python3 backfill_matchup_results.py` |
| `analyze_historic_favorites.py` | Rebuild historic tables/charts under `data/results/`. Flags: `--out-csv`, `--out-txt`, `--out-png`, `--out-csv-spread`, `--out-png-spread`; `--no-plot` skips PNGs. `python3 analyze_historic_favorites.py` |
| `verify_matchup_data.py` | Checks internal math (`net_hitting_obp`, `net_pitching_obp`, or legacy `matchup`), two rows per `game_pk`, W/L/T consistency, and odds pairs. `--api-sample N` spot-checks `results` vs the API. `python3 verify_matchup_data.py` |

## Verifying data

Run **`python3 verify_matchup_data.py`** on your `data/` tree.

- **New schema:** `net_hitting_obp ≈ hitting_obp − opponent_hitting_obp` and `net_pitching_obp ≈ pitching_obp − opponent_pitching_obp`.
- **Legacy schema:** `matchup ≈ obp − opponent_obp` (older files only).
- Each `game_pk` should have **two** rows; **W/L** (or **T/T**) should be consistent; **`favorite` / `not favorite`** pairs should be coherent.

It no longer requires the two `matchup` / net values to be exact opposites (that was only true when both sides used the same hitting-minus-hitting construction).

## Output files

Daily CSVs live under **`data/`**. Historic analysis defaults to **`data/results/`**.

### Daily

| File | Contents |
| ---- | -------- |
| `data/YYYY-MM-DD.csv` | `team_id`, `team_name`, `hitting_obp`, `pitching_obp` |
| `data/YYYY-MM-DD_matchups.csv` | `game_pk`, `team`, `opponent`, hitting/pitching raw + opponent columns, `net_hitting_obp`, `net_pitching_obp`, `odds`; past dates add **`results`** after backfill |

### Historic (`data/results/`)

| File | Contents |
| ---- | -------- |
| `historic_matchup_odds_results.csv` | Cross-tab: **`odds_role`** × **hitting edge sign** (`matchup_sign` column name kept for compatibility), win rates |
| `historic_matchup_odds_results.txt` | Summary text + pointers to other outputs |
| `historic_matchup_odds_results.png` | Heatmap: moneyline side × hitting edge sign |
| `historic_matchup_spread_by_odds.csv` | Binned **`net_hitting_obp`** (or legacy `matchup`) × favorite / not_favorite |
| `historic_matchup_spread_winrate.png` | Heatmap for that table |
| `historic_marginals_by_bucket.csv` | Win rates for **`odds` alone**, **hitting sign alone**, **pitching sign alone** (pitching block only if any input file has `net_pitching_obp`) |
| `historic_odds_vs_pitching_sign.csv` / `.png` | Moneyline × **pitching** edge sign |
| `historic_pitching_spread_by_odds.csv` / `historic_pitching_spread_winrate.png` | Binned **`net_pitching_obp`** × moneyline side |
| `historic_hitting_x_pitching_sign.csv` / `.png` | 4×4 **hitting × pitching** sign buckets (all moneyline roles combined) |
| `historic_odds_hitting_pitching_combo.csv` | Full **odds × hitting × pitching** sign grid |

If no matchup file includes **`net_pitching_obp`**, pitching-specific and combo artifacts are skipped; hitting-only outputs still run.

`game_pk` is the MLB Stats API game identifier.

## Data sources

- **MLB:** `https://statsapi.mlb.com/api/v1` (team hitting + pitching stats, schedule / final lines for backfill)
- **ESPN:** public MLB scoreboard and game summary (`pickcenter` moneylines)

## Caveats

- All OBP figures are **season-to-date** snapshots from the day the data was fetched, not restated when you backfill **`results`** later.
- **`net_hitting_obp`** and **`net_pitching_obp`** compare **whole-season** team rates, not the specific opponent’s lineup or starter that day.
- Moneylines are **one** sportsbook row from ESPN, not a consensus.
- ESPN may omit `pickcenter` for some games → **`odds` = `unknown`**.
- One **HTTP request per ESPN game** on the slate for summary odds (fine for a daily run).
- Historic samples depend on how many dated `*_matchups.csv` files include **`results`**.
- Heatmap bins are fixed; small **`n`** per cell means noisy win rates—descriptive only, not a calibrated model.
