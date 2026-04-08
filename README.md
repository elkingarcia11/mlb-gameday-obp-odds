# MLB gameday odds edge finder

**mlb-gameday-odds-edge-finder** — a small Python script that pulls **MLB team on-base percentage (OBP)** for the current season, loads **today’s schedule**, and writes CSV files that list each team’s OBP edge against its opponent for the day. It also labels each side of a game as **betting favorite**, **not favorite**, or **equal** using **American moneylines** from ESPN’s public game data.

## What it does

1. **Team OBP** — Fetches every MLB club’s season hitting OBP from the official **MLB Stats API** (the same backend as [mlb.com team stats](https://www.mlb.com/stats/team/on-base-percentage)).
2. **Today’s games** — Fetches the schedule for **today’s calendar date** from the same Stats API (equivalent to the league schedule for that day).
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

- **Python 3.9+** (uses `urllib` and the standard library only — no `pip install` needed)

## How to run

From the project directory:

```bash
python3 main.py
```

The script uses **today’s date** on your machine for the schedule, season year, and output filenames.

## Output files

Both files are written under `data/`:

| File | Contents |
|------|-----------|
| `data/YYYY-MM-DD.csv` | All teams: `team_id`, `team_name`, `obp` |
| `data/YYYY-MM-DD_matchups.csv` | One row per team per game: `game_pk`, `team`, `opponent`, `obp`, `opponent_obp`, `matchup`, `odds` |

`game_pk` is the MLB Stats API game identifier (useful if two games share the same matchup on a doubleheader day).

## Data sources

- **MLB:** `https://statsapi.mlb.com/api/v1` (team hitting stats, schedule)
- **ESPN:** public MLB scoreboard and game summary endpoints (moneylines in `pickcenter`)

## Caveats

- OBP is **season-to-date** from the Stats API, not a projection or ballpark-adjusted figure.
- Moneylines are **one sportsbook row** from ESPN’s feed, not a market consensus.
- ESPN may omit `pickcenter` for some games; those rows get **`odds` = `unknown`**.
- The script performs **one HTTP request per ESPN game** on the slate for that day to read summary odds (fine for a daily run, not ideal for tight loops).
