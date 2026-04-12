# MLB gameday odds edge finder

**mlb-gameday-odds-edge-finder** — a small Python project that pulls **MLB team on-base percentage (OBP)** for the current season, loads **today’s schedule**, and writes CSV files that list each team’s OBP edge against its opponent for the day. It labels each side of a game as **betting favorite**, **not favorite**, or **equal** using **American moneylines** from ESPN’s public game data.

Each time you run **`main.py`**, it also **backfills final scores** into older matchup files and **refreshes historic win/loss summaries** (tables plus an optional chart).

## What it does

### Daily pipeline (`main.py`)

When you run `main.py`, steps run in this order:

1. **Backfill results** — Scans `data/*_matchups.csv` for dates **before today**. If a file has no `results` column yet, the script loads that day’s schedule from the **MLB Stats API**, maps each row’s `game_pk` and `team` to **W**, **L**, or **T** (ties), and rewrites the CSV with a trailing **`results`** column. Files that already include `results`, and **today’s** matchup file, are left unchanged by this step.
2. **Historic analysis** — Recomputes **`data/results/historic_matchup_odds_results.csv`**, **`.txt`**, and **`.png`**. The analysis crosses **moneyline role** (`odds`: favorite vs not favorite vs other) with **OBP edge sign** (`matchup` &lt; 0, = 0, &gt; 0, or unparsable) and summarizes **actual `results`** (win rate **W / (W+L)**). The PNG needs **matplotlib** (see [Requirements](#requirements)); if matplotlib is missing, CSV and TXT are still written. The `data/results/` directory is created automatically when those files are written.
3. **Today’s snapshot** — Same behavior as before: team OBP CSV, today’s matchup CSV (no `results` column yet for the current slate).

### Core matchup logic (unchanged)

1. **Team OBP** — Fetches every MLB club’s season hitting OBP from the official **MLB Stats API** (the same backend as [mlb.com team stats](https://www.mlb.com/stats/team/on-base-percentage)).
2. **Today’s games** — Fetches the schedule for **today’s calendar date** from the same Stats API.
3. **Matchup file** — For each scheduled game (excluding cancelled/postponed games), it emits **two rows** (away perspective and home perspective). Each row includes:
   - `obp` / `opponent_obp` — season OBP for that team and its opponent  
   - `matchup` — that team’s OBP minus the opponent’s OBP  
   - `odds` — see below  
   Rows are **sorted by `matchup` descending** (largest OBP advantage first).
4. **Betting `odds` column** — Uses ESPN’s scoreboard plus per-game **summary** JSON. The first usable **`pickcenter`** block (often **DraftKings**) supplies away/home **moneylines**. For each row, the script compares this team’s line to the opponent’s (American odds):
   - **`favorite`** — this team’s number is **less than** the opponent’s (e.g. `-150` vs `+130`)
   - **`not favorite`** — this team’s number is **greater** than the opponent’s
   - **`equal`** — same line
   - **`unknown`** — no moneylines available or the game couldn’t be matched to ESPN’s slate

Games are matched to ESPN by the **pair of team names** (with a simple normalized-name fallback if wording differs slightly).

## Requirements

- **Python 3.10+** for `main.py`, `backfill_matchup_results.py`, and the analysis script (standard library plus `urllib`; modern type syntax).
- **Optional (for the historic PNG):** **matplotlib**, listed in `requirements.txt`. On macOS/Homebrew Python (**PEP 668**), install into a **virtual environment** rather than the system interpreter:

  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python main.py
  ```

The repository **`.gitignore`** ignores `.venv/`.

## How to run

### Full daily run (recommended)

From the project directory, using the venv if you want charts:

```bash
.venv/bin/python main.py
```

Or with system Python (CSV/TXT analysis still runs; PNG is skipped if matplotlib is not installed):

```bash
python3 main.py
```

The script uses **today’s date** on your machine for the schedule, season year, and output filenames.

### Standalone utilities

| Script | Purpose |
|--------|--------|
| `backfill_matchup_results.py` | Only backfills `results` on past `data/YYYY-MM-DD_matchups.csv` files (same rules as step 1 in `main.py`). Run from project root: `python3 backfill_matchup_results.py` |
| `analyze_historic_favorites.py` | Only rebuilds historic odds × matchup × results summaries and plot. Defaults: `--out-csv`, `--out-txt`, `--out-png` under `data/results/historic_matchup_odds_results.*`. Use `--no-plot` to skip PNG. Run: `python3 analyze_historic_favorites.py` |

## Output files

Daily team and matchup CSVs live under `data/`. Historic analysis outputs live under **`data/results/`** unless you override paths on the analysis script.

| File | Contents |
|------|----------|
| `data/YYYY-MM-DD.csv` | All teams: `team_id`, `team_name`, `obp` |
| `data/YYYY-MM-DD_matchups.csv` | One row per team per game: `game_pk`, `team`, `opponent`, `obp`, `opponent_obp`, `matchup`, `odds`. Past dates, after backfill, also include **`results`** (`W` / `L` / `T`, or blank if unavailable). |
| `data/results/historic_matchup_odds_results.csv` | Cross-tab: **`odds_role`** × **`matchup_sign`** with wins, losses, ties, no-result counts, decided games, and **win_rate_wl_only** (W / (W+L)). |
| `data/results/historic_matchup_odds_results.txt` | Human-readable version of the same aggregates (non-empty buckets only). |
| `data/results/historic_matchup_odds_results.png` | Heatmap of win rate by favorite vs not favorite (rows) and matchup sign (columns). Requires matplotlib. |

`game_pk` is the MLB Stats API game identifier (useful if two games share the same matchup on a doubleheader day).

## Data sources

- **MLB:** `https://statsapi.mlb.com/api/v1` (team hitting stats, schedule — including final scores for backfill)
- **ESPN:** public MLB scoreboard and game summary endpoints (moneylines in `pickcenter`)

## Caveats

- OBP is **season-to-date** from the Stats API, not a projection or ballpark-adjusted figure.
- Moneylines are **one sportsbook row** from ESPN’s feed, not a market consensus.
- ESPN may omit `pickcenter` for some games; those rows get **`odds` = `unknown`**.
- The script performs **one HTTP request per ESPN game** on the slate for that day to read summary odds (fine for a daily run, not ideal for tight loops).
- **Historic analysis** is only as complete as the number of past `*_matchups.csv` files that already include a **`results`** column; until a calendar day has finished and been backfilled, that day does not contribute to the aggregates.
