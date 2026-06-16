# MLB gameday — hitting & pitching OBP vs moneylines

**Repository:** `mlb-gameday-obp-odds`

Daily Python pipeline: **MLB Stats API** season team rates (**hitting OBP** and **OBP allowed** on the pitching line), **today’s** schedule, and **ESPN** American moneylines for the slate.
It writes dated **team** and **matchup** CSVs with hitting/pitching edges, numeric **moneylines**, and **`favorite` / `not favorite`** labels.
For past dates it **backfills** **W / L / T**, then recomputes **historic analysis** under `data/results/` — both the original OBP-vs-odds-role charts and **betting analytics** (ROI, calibration, scatter, and related charts) when moneylines and results are available.

Running `main.py` backfills finished games into older `*_matchups.csv` rows (`results`), rebuilds all analysis under `data/results/`, then writes **today’s** team and matchup files.

## What it does

### Daily pipeline (`main.py`)

1. **Backfill results** — Scans `data/*_matchups.csv` for dates **before today**. If a file has no `results` column yet, loads that day’s schedule from the **MLB Stats API**, maps each row’s `game_pk` and `team` to **W**, **L**, or **T**, and rewrites the CSV with a trailing `results` column. Files that already include `results`, and **today’s** matchup file, are skipped.
2. **Historic analysis** — Two **separate** layers under `data/results/` (no combined hitting×pitching charts):
   - **OBP vs odds role** (`analyze_historic_favorites.py`) — parallel hitting and pitching: odds role × edge sign, binned edge × favorite/not favorite, and (when `moneyline` exists) binned edge × moneyline bucket and sign × moneyline bucket.
   - **Betting analytics** (`analyze_betting_charts.py`) — parallel hitting and pitching ROI/win-rate suites when `moneyline` + `results` exist.
3. **Today’s snapshot** — Team rate CSV (`hitting_obp`, `pitching_obp`) and today’s matchup CSV (includes `moneyline` columns; no `results` yet for the live slate).

### Stats and matchup columns

**MLB Stats API** (`https://statsapi.mlb.com/api/v1`):

- `group=hitting` — each team’s season **batting** OBP (same idea as [mlb.com team hitting OBP](https://www.mlb.com/stats/team/on-base-percentage)).
- `group=pitching` — each team’s `obp` is **OBP allowed to all opposing hitters** that season (staff/defense line, not the lineup’s OBP).

`data/YYYY-MM-DD.csv` (one row per team):

| Column         | Meaning                                      |
| -------------- | -------------------------------------------- |
| `team_id`      | MLB club id                                  |
| `team_name`    | Club name                                    |
| `hitting_obp`  | Season batting OBP                           |
| `pitching_obp` | Season OBP **allowed** (pitching group stat) |

`data/YYYY-MM-DD_matchups.csv` (two rows per scheduled game — away and home team-sides; cancelled/postponed games omitted):

| Column                  | Meaning                                                                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `game_pk`               | MLB game id                                                                                                              |
| `team` / `opponent`     | This row’s club and opponent                                                                                             |
| `hitting_obp`           | This team’s season batting OBP                                                                                           |
| `opponent_hitting_obp`  | Opponent’s season batting OBP                                                                                            |
| `pitching_obp`          | This team’s season OBP **allowed**                                                                                       |
| `opponent_pitching_obp` | Opponent’s season OBP **allowed**                                                                                        |
| `net_hitting_obp`       | `hitting_obp − opponent_hitting_obp` (**higher** = better lineup edge)                                                   |
| `net_pitching_obp`      | `pitching_obp − opponent_pitching_obp` (**lower / more negative** = you allow less OBP than they do = better staff edge) |
| `moneyline`             | This team’s American moneyline from ESPN (`-150`, `+130`, or blank if missing)                                           |
| `opponent_moneyline`    | Opponent’s American moneyline (same source)                                                                              |
| `odds`                  | `favorite` / `not favorite` / `equal` / `unknown` (derived from the two moneylines; see below)                           |
| `results`               | After backfill on past dates: `W` / `L` / `T` or blank                                                                   |

Rows are sorted by `net_hitting_obp` descending, then `net_pitching_obp` ascending (stronger hitting edge first; for ties, lean toward the better relative pitching number).

**Betting `odds` and moneylines** — ESPN scoreboard + per-game **summary** `pickcenter` (often **DraftKings**). American moneylines are stored in `moneyline` / `opponent_moneyline`. The `odds` column is derived: `favorite` if this team’s line is **less than** the opponent’s (e.g. `-150` vs `+130`), `not favorite` if greater, `equal` if tied, `unknown` if missing or the game could not be matched by team names.

Older matchup CSVs may still use legacy columns (`obp`, `opponent_obp`, `matchup`) and may lack `moneyline` columns (see [Compatibility](#compatibility-with-existing-data-and-gcs)). Historic analysis prefers `net_hitting_obp` when present, else `matchup`, for hitting-edge charts.

## Compatibility with existing data and GCS

The bucket layout is unchanged: objects live under `gs://BUCKET/data/...` (dated CSVs plus `data/results/`). `gcs_sync.py` downloads the full prefix before the run and uploads the full local `data/` tree afterward — including new betting chart outputs.

| What you already have | OBP vs odds-role charts | Betting analytics charts |
| --------------------- | ----------------------- | ------------------------ |
| `net_hitting_obp`, `odds`, `results` | Yes | No — needs numeric `moneyline` |
| Above + `moneyline` columns | Yes | Yes (W/L rows only) |
| Legacy `obp` / `matchup` only | Partial (hitting-only) | No |
| No `results` yet | Skipped until backfill | Skipped until backfill |

**Gradual rollout:** matchup files written **before** the moneyline change keep working for backfill and OBP-vs-role analysis. They are not modified retroactively — backfill only *appends* `results`. New `moneyline` / `opponent_moneyline` columns appear on **new** daily snapshots only. Betting analytics fill in as those files accumulate; older dates without moneylines are ignored by `analyze_betting_charts.py` (not an error).

**Cloud Run / Docker:** the image bundles `main.py`, `backfill_matchup_results.py`, `analyze_historic_favorites.py`, `analyze_betting_charts.py`, and `gcs_sync.py`. After pulling these changes, **rebuild and redeploy** the job image so the container includes the betting module.

## Requirements

- **Python 3.10+** for `main.py`, `backfill_matchup_results.py`, and the analysis scripts (stdlib + `urllib`).
- **Optional (PNGs):** **matplotlib** in `requirements.txt`. On macOS/Homebrew Python (**PEP 668**), use a venv:
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python main.py
  ```

The repository `.gitignore` ignores `.venv/` and `data/`.

## How to run

### Full daily run (recommended)

```bash
.venv/bin/python main.py
```

or `python3 main.py` (PNGs skipped if matplotlib is missing).

The script uses **today’s calendar date in US Eastern** (`America/New_York`, EST/EDT) for the schedule, season year, and output filenames.

### GCS mode (automation / Cloud Run Jobs)

Syncs the `data/` tree from a bucket, runs the pipeline, then uploads `data/` back (object prefix `data/` in the bucket).

```bash
export GCS_BUCKET=your-bucket-name
.venv/bin/python main.py --storage gcs
# or: .venv/bin/python main.py --storage gcs --gcs-bucket your-bucket-name
```

Requires `google-cloud-storage` (see `requirements.txt`) and credentials that can read and write those objects (e.g. Cloud Run job’s **execution service account** with Storage access on the bucket).

### Standalone utilities

| Script                          | Purpose                                                                                                                                                                                                                           |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backfill_matchup_results.py`   | Backfill `results` only on past `data/YYYY-MM-DD_matchups.csv` (same rules as step 1). `python3 backfill_matchup_results.py`                                                                                                      |
| `analyze_historic_favorites.py` | Rebuild OBP-vs-odds-role tables/charts under `data/results/`. Flags: `--out-csv`, `--out-txt`, `--out-png`, `--out-csv-spread`, `--out-png-spread`; `--no-plot` skips PNGs. `python3 analyze_historic_favorites.py`             |
| `analyze_betting_charts.py`     | Rebuild ROI / win-rate / calibration charts (`moneyline` + `results` required per row; `--no-plot` skips PNGs). `python3 analyze_betting_charts.py`                                                                               |
| `verify_matchup_data.py`        | Checks internal math (`net_hitting_obp`, `net_pitching_obp`, or legacy `matchup`), two rows per `game_pk`, W/L/T consistency, odds pairs, and moneyline ↔ `odds` consistency when moneylines exist. `--api-sample N` spot-checks `results` vs the API. `python3 verify_matchup_data.py` |

## Docker and Cloud Run Jobs

The `Dockerfile` is meant for **Cloud Run Jobs**: one container runs `python main.py --storage gcs` until it exits (no web server or `PORT`).

Repository root `cloudbuild.yaml` defines a **Cloud Build** pipeline that builds that Dockerfile and pushes to Artifact Registry on each trigger run (see below).

### Cloud Build: GitHub push → Artifact Registry (recommended)

Use a **Cloud Build trigger** so pushes to GitHub build and push the image without using your laptop.

1. **Enable the [Cloud Build API](https://console.cloud.google.com/apis/library/cloudbuild.googleapis.com)** on your GCP project.
2. **Grant Artifact Registry write access to Cloud Build.** The build runs as
   `PROJECT_NUMBER@cloudbuild.gserviceaccount.com`. Give it **Artifact Registry Writer** (`roles/artifactregistry.writer`) on the project (or a narrower role on your Docker repo). Find `PROJECT_NUMBER`:
3. **Connect GitHub** in the console: **Cloud Build → Triggers → Connect repository** (install the Cloud Build GitHub app / link the repo). Guide: [Connect to a GitHub third-party repository](https://cloud.google.com/build/docs/automating-builds/github/connect-repo-github).
4. **Create a trigger**
   - **Event:** Push to a branch.
   - **Branch (regex):** `^main$` is recommended so only `main` updates the `:latest` tag produced by `cloudbuild.yaml`.
   - **Build configuration:** **Cloud Build configuration file (yaml or json)** — path `cloudbuild.yaml`.
   - **Substitutions (optional):** in the trigger, you can override `_REGION`, `_AR_REPO`, or `_IMAGE_NAME` if they differ from the defaults in `cloudbuild.yaml`.
5. **Push to `main`** (or click **Run** on the trigger). A successful build publishes `.../daily-job:$SHORT_SHA` and `.../daily-job:latest`. Point the Cloud Run Job at `...:latest` for a stable URL that tracks `main`, or pin `:$SHORT_SHA` for an exact revision.

**If `docker push` fails with `invalid_grant`:** run `gcloud auth login` again, then `gcloud auth configure-docker REGION-docker.pkg.dev`.

**Test `cloudbuild.yaml` without GitHub** (you must pass `SHORT_SHA`; it is set automatically on trigger runs):

```bash
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions=SHORT_SHA=$(git rev-parse --short HEAD)
```

### Artifact Registry: local Docker login (manual pushes only)

Use the [Google Cloud SDK](https://cloud.google.com/sdk) when you still want to push from your machine.

1. **Install and initialize** (if you have not already):
   ```bash
   gcloud init
   gcloud auth login
   ```
2. **Configure Docker** for the Artifact Registry **hostname** for your region. Use only `REGION-docker.pkg.dev` — do **not** append `/project/repo` to this command (that path belongs on `docker build` / `docker push` tags only).
   Example for `us-east4`:
   For a different region, substitute its hostname (e.g. `us-east1-docker.pkg.dev`). More detail: [Configure authentication for Docker](https://cloud.google.com/artifact-registry/docs/docker/authentication).
3. **Build and push** the image. Set variables to match your GCP **project**, Artifact Registry **repository id** (from the console), **region**, image name, and tag:
   ```bash
   PROJECT_ID=elkin-garcia-workspace
   REGION=us-east4
   REPO=mlb-gameday-obp-odds
   IMAGE=daily-job
   TAG=$(git rev-parse --short HEAD)

   docker build -t "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE}:${TAG}" .
   docker push "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE}:${TAG}"
   ```
   Use that full URI as the container image when you create or update the Cloud Run Job.

### Cloud Run Job (after the image exists)

1. **Create or update the job** in the Google Cloud console (or `gcloud`): point the job at that image, **one task** (default parallelism is fine for this workload), and a **task timeout** long enough for MLB/ESPN calls, GCS download/upload, and analysis (often **10–15 minutes** is comfortable).
2. **Job settings**
   - **Environment variables:** set `GCS_BUCKET` to your bucket (same layout as local: objects under `gs://BUCKET/data/...`).
   - **Service account:** the identity the job runs as needs permission to **list, read, and create** objects under that prefix (e.g. **Storage Object Admin** on the bucket for a simple setup).
   - **Command / args:** leave the image default unless you intentionally override it.
3. **Scheduling:** use **Cloud Scheduler** (or manual **Execute**) to run the job. For an 8:00 Eastern trigger, set the scheduler’s **time zone** to `America/New_York`; the app’s “today” for the slate is already **US Eastern**.

## Verifying data

Run `python3 verify_matchup_data.py` on your `data/` tree.

- **New schema:** `net_hitting_obp ≈ hitting_obp − opponent_hitting_obp` and `net_pitching_obp ≈ pitching_obp − opponent_pitching_obp`.
- **Legacy schema:** `matchup ≈ obp − opponent_obp` (older files only).
- Each `game_pk` should have **two** rows; **W/L** (or **T/T**) should be consistent; `favorite` / `not favorite` pairs should be coherent.
- When `moneyline` columns exist, `odds` should match the derived role from the two moneylines.

It no longer requires the two `matchup` / net values to be exact opposites (that was only true when both sides used the same hitting-minus-hitting construction).

## Output files

Daily CSVs live under `data/`. Historic analysis defaults to `data/results/`.

### Daily

| File                           | Contents                                                                                                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `data/YYYY-MM-DD.csv`          | `team_id`, `team_name`, `hitting_obp`, `pitching_obp`                                                                                                              |
| `data/YYYY-MM-DD_matchups.csv` | `game_pk`, `team`, `opponent`, hitting/pitching raw + opponent columns, `net_hitting_obp`, `net_pitching_obp`, `moneyline`, `opponent_moneyline`, `odds`; past dates add `results` after backfill |

### Historic — win rate analysis (`data/results/`)

Hitting and pitching are **separate chart families**. Moneyline buckets: `+150+`, `+100–+149`, `−100–−149`, `−150+`.

| Hitting | Pitching (needs `net_pitching_obp`) |
| ------- | ----------------------------------- |
| `historic_matchup_odds_results.csv` / `.png` — odds role × hitting sign | `historic_matchup_pitching_odds_results.csv` / `.png` — odds role × pitching sign |
| `historic_odds_vs_hitting_sign.csv` / `.png` | `historic_odds_vs_pitching_sign.csv` / `.png` |
| `historic_matchup_spread_by_odds.csv` / `historic_matchup_spread_winrate.png` — binned hitting edge × favorite/not favorite | `historic_pitching_spread_by_odds.csv` / `historic_pitching_spread_winrate.png` — binned pitching edge × favorite/not favorite |
| `historic_hitting_spread_by_moneyline.csv` / `.png` — binned hitting edge × moneyline bucket | `historic_pitching_spread_by_moneyline.csv` / `.png` — binned pitching edge × moneyline bucket |
| `historic_hitting_sign_by_moneyline.csv` / `.png` | `historic_pitching_sign_by_moneyline.csv` / `.png` |

Also: `historic_marginals_by_bucket.csv`, `historic_matchup_odds_results.txt`.

**Removed:** combined `historic_hitting_x_pitching_sign` and `historic_odds_hitting_pitching_combo`.

Moneyline-bucket charts require a `moneyline` column; lines outside the four buckets are omitted from those aggregates only.

### Historic — betting analytics (`moneyline` + `results` required)

Separate suites for **net hitting OBP** and **net pitching OBP**:

| Chart type | Hitting prefix | Pitching prefix |
| ---------- | -------------- | --------------- |
| Edge vs win rate | `historic_net_hitting_obp_vs_winrate` | `historic_net_pitching_obp_vs_winrate` |
| Edge vs ROI | `historic_net_hitting_obp_vs_roi` | `historic_net_pitching_obp_vs_roi` |
| Edge × moneyline win rate | `historic_net_hitting_obp_x_moneyline_winrate` | `historic_net_pitching_obp_x_moneyline_winrate` |
| Edge × moneyline ROI | `historic_net_hitting_obp_x_moneyline_roi` | `historic_net_pitching_obp_x_moneyline_roi` |
| Actual vs implied | `historic_net_hitting_obp_actual_vs_implied` | `historic_net_pitching_obp_actual_vs_implied` |
| Scatter | `historic_net_hitting_obp_vs_moneyline_scatter` | `historic_net_pitching_obp_vs_moneyline_scatter` |
| Calibration | `historic_net_hitting_obp_calibration_curve` | `historic_net_pitching_obp_calibration_curve` |
| Team ROI heatmap | `historic_team_net_hitting_obp_roi` | `historic_team_net_pitching_obp_roi` |
| Value score tiers | `historic_net_hitting_obp_value_score_roi` | `historic_net_pitching_obp_value_score_roi` |

Summary: `historic_betting_charts.txt`. Rows missing W/L, net edge, or moneyline are skipped per edge type.

**ROI** uses flat **$100** stakes per team-side. **Implied probability** from American odds: `-150 → 60%`, `+120 → 45.5%`.

`game_pk` is the MLB Stats API game identifier.

## Data sources

- **MLB:** `https://statsapi.mlb.com/api/v1` (team hitting + pitching stats, schedule / final lines for backfill)
- **ESPN:** public MLB scoreboard and game summary (`pickcenter` moneylines)

## Caveats

- All OBP figures are **season-to-date** snapshots from the day the data was fetched, not restated when you backfill `results` later.
- `net_hitting_obp` and `net_pitching_obp` compare **whole-season** team rates, not the specific opponent’s lineup or starter that day.
- Moneylines are **one** sportsbook row from ESPN, not a consensus; lines are captured at fetch time (not guaranteed to be closing lines unless you run near first pitch).
- ESPN may omit `pickcenter` for some games → `odds` = `unknown` and blank `moneyline` columns.
- One **HTTP request per ESPN game** on the slate for summary odds (fine for a daily run).
- Historic sample sizes depend on how many dated `*_matchups.csv` files include `results` (and `moneyline` for betting charts).
- Heatmap bins and calibration “expected” values are fixed heuristics; small **n** per cell means noisy rates — descriptive only, not a calibrated model.
- Pre-moneyline historic files remain valid; betting charts simply stay empty until enough post-change data with results accumulates.
