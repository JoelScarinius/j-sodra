# J-Södra Analytics

Football intelligence platform for Jönköpings Södra.

This repository contains the data pipeline and publishing contract used by the Lovable dashboard. The pipeline fetches football data through Supabase Edge Functions, builds analytics reports, creates visualisations, and publishes a modular `reports/` folder that the frontend can read.

---

## 1. What this project does

The goal is to give J-Södra a simple analytics hub for:

- understanding upcoming opponents,
- reviewing J-Södra's own performance,
- preparing match-specific insights,
- comparing team and opponent tendencies,
- publishing repeatable analytics to the Lovable frontend.

The system is designed so multiple collaborators can work on separate dashboard sections without editing the same large file.

---

## 2. System overview

```text
GitHub Actions
  -> runs fetch_football_data.py

fetch_football_data.py
  -> small command-line entrypoint only

pipeline/orchestrator.py
  -> coordinates the pipeline
  -> creates shared PipelineContext
  -> runs registered analytics sections
  -> writes reports/index.json
  -> uploads generated artifacts when enabled

pipeline/sections/*.py
  -> one dashboard section per file
  -> each collaborator usually owns one section

pipeline/publishing.py
  -> writes JSON/CSV files
  -> builds frontend file references
  -> uploads artifacts to Supabase Storage

Lovable frontend
  -> reads reports/index.json
  -> follows section references from index.sections
```

---

## 3. Important design principles

### 3.1 Keep the entrypoint small

`fetch_football_data.py` must stay small.

It should only:

1. parse command-line arguments,
2. load settings,
3. call the pipeline orchestrator.

Do **not** add feature logic, Wyscout logic, plotting logic, or section-specific logic to `fetch_football_data.py`.

### 3.2 Data access belongs in `DataService`

All Wyscout/Supabase data access should go through `pipeline/data_service.py`.

Collaborators should normally not call the Wyscout API directly from a section file. Instead, sections should use the shared datasets available through `PipelineContext`.

### 3.3 Publishing belongs in `publishing.py`

Sections should write files locally, but they should not upload directly to Supabase Storage.

The normal flow is:

1. section creates JSON/CSV/PNG files under `reports/<section_name>/`,
2. section returns a `SectionResult`,
3. orchestrator collects all files,
4. `pipeline/publishing.py` uploads files to Supabase Storage if upload is enabled.

### 3.4 One section, one responsibility

Each dashboard area should live in one file under `pipeline/sections/`.

Examples:

```text
pipeline/sections/open_play.py
pipeline/sections/free_kicks.py
pipeline/sections/throw_ins.py
pipeline/sections/defensive.py
```

A collaborator working on open play should mostly work in `pipeline/sections/open_play.py`.

---

## 4. Should section files be self-contained?

Short answer: **mostly yes, but not completely**.

A section file should be self-contained as a dashboard feature. That means the section file should contain or call the code needed to build that section's metrics, storylines, data exports, and plots.

However, a section file should **not** duplicate shared infrastructure.

Use this rule:

```text
Section-specific football logic        -> pipeline/sections/<section_name>.py
Reusable football calculations         -> pipeline/analytics.py
General helper functions               -> pipeline/common.py
Wyscout/Supabase fetching              -> pipeline/data_service.py
Writing JSON/CSV and file references   -> pipeline/publishing.py
Pitch/plot helper functions            -> pipeline/visualisations/ or pipeline/plots.py
```

### Recommended section structure

For small sections, it is fine to keep metrics and plotting in the same section file.

For larger sections, split helper logic into a submodule, for example:

```text
pipeline/sections/open_play.py
pipeline/visualisations/open_play_maps.py
```

or:

```text
pipeline/sections/open_play.py
pipeline/open_play/metrics.py
pipeline/open_play/plots.py
```

But do not over-engineer too early. Start with one section file, then split only when the file becomes hard to read.

---

## 5. Adding a new analytics section

Analytics features are added as modular section files under:

```text
pipeline/sections/
```

Every section must implement:

```python
def build_section(context) -> SectionResult:
    ...
```

Every section must return:

```python
SectionResult(
    name="section_name",
    files=[...],
    index_entry={...},
)
```

### Contributor checklist

Before opening a pull request, make sure the section:

- [ ] lives under `pipeline/sections/`,
- [ ] has a clear `SECTION_NAME`,
- [ ] implements `build_section(context)`,
- [ ] uses the shared `PipelineContext`,
- [ ] writes files only under `reports/<section_name>/`,
- [ ] returns all generated files in `SectionResult.files`,
- [ ] adds frontend references through `SectionResult.index_entry`,
- [ ] uses `pipeline/publishing.py` helpers for writing JSON/CSV and refs,
- [ ] does not upload directly to Supabase,
- [ ] does not fetch directly from Wyscout unless agreed,
- [ ] uses the shared visual style from `pipeline/settings.py`,
- [ ] uses `mplsoccer` for pitch-based football visualisations where possible,
- [ ] is registered in `pipeline/registry.py`,
- [ ] has been tested locally or in GitHub Actions.

### Minimal section example

```python
from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json


SECTION_NAME = "open_play"


def build_section(context) -> SectionResult:
    output_path = context.settings.report_path(SECTION_NAME, "analysis.json")

    payload = {
        "generated_at": context.generated_at,
        "section": SECTION_NAME,
        "status": "in_progress",
        "team": {
            "id": context.team_id,
            "name": context.team_name,
            "summary": {},
            "metrics": [],
            "storylines": [],
        },
        "next_opponent": {
            "id": context.opponent_id,
            "name": context.opponent_name,
            "summary": {},
            "metrics": [],
            "storylines": [],
        },
        "files": {
            "data": {},
            "plots": {},
        },
    }

    write_json(output_path, payload)

    return SectionResult(
        name=SECTION_NAME,
        files=[output_path],
        index_entry={
            "analysis": build_ref(context.settings, output_path),
        },
    )
```

---

## 6. Plotting and visual design rules

The dashboard should look and feel like one product. All sections must follow the same club-inspired visual language.

### 6.1 Required colour palette

The palette is defined in `pipeline/settings.py` and should be reused everywhere.

```python
PLOT_STYLE = {
    "bg": "#002418",
    "line": "#f5f0da",
    "accent": "#d4af37",
    "accent_2": "#6fcf97",
    "muted": "#8ad6b4",
    "danger": "#f07167",
    "text": "#f5f0da",
}
```

Usage guidance:

- `bg` — dashboard and plot background,
- `line` — pitch lines, chart lines, high-contrast details,
- `accent` — J-Södra gold, active states, key values,
- `accent_2` — positive secondary football values,
- `muted` — labels and supporting information,
- `danger` — negative values, goals conceded, warnings,
- `text` — readable text on dark background.

Do not invent a new palette inside a section. If new colours are needed, add them centrally in `pipeline/settings.py`.

### 6.2 Use `mplsoccer` for football pitch plots

Use `mplsoccer` as much as possible for pitch-based football visualisations.

Examples of plots that should normally use `mplsoccer`:

- shot maps,
- pass maps,
- carry maps,
- progression maps,
- defensive action maps,
- pressure maps,
- set-piece maps,
- throw-in maps,
- corner delivery maps.

Matplotlib can still be used for normal charts such as:

- bar charts,
- line charts,
- stacked bars,
- tables,
- trend charts.

### 6.3 Plot file rules

Plots should be written under:

```text
reports/<section_name>/plots/
```

Data exports should be written under:

```text
reports/<section_name>/data/
```

The section should include plot/data references in its `analysis.json` payload and in `SectionResult.index_entry` when useful.

---

## 7. Frontend output contract

The frontend should start by loading:

```text
reports/index.json
```

The frontend should then read `sections` from `reports/index.json` and fetch the files listed there.

Do not rely on old root-level payload files.

Current report tree:

```text
reports/
  index.json
  entities/
    team.json
    next_opponent.json
  matchup/
    current.json
  overview/
    team.json
    next_opponent.json
  fixtures/
    upcoming.json
  forms/
    recent_form.json
  head_to_head/
    overview.json
    plots/
  corners/
    analysis.json
    data/
    plots/
  open_play/
    analysis.json
    data/
    plots/
  free_kicks/
    analysis.json
    data/
    plots/
  throw_ins/
    analysis.json
    data/
    plots/
  defensive/
    analysis.json
    data/
    plots/
  exports/
    competitions/
  upload_manifest.json
```

`reports/index.json` is the frontend bootstrap file.

---

## 8. Running locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env` file. Do not commit secrets.

```bash
SUPABASE_FUNCTION_URL=https://<project-ref>.supabase.co/functions/v1/wyscout-proxy
SUPABASE_ANON_KEY=your_supabase_anon_key

FILTER_TO_ACTIVE_SEASON=1
ENABLE_PREVIOUS_SEASON_COMPLEMENT=0
H2H_FALLBACK_TO_PREVIOUS_SEASON=1
OUTPUT_DIR=.
REPORTS_DIR=reports
```

Run the pipeline:

```bash
python fetch_football_data.py
```

Force a full upstream refresh:

```bash
python fetch_football_data.py --force-refresh
```

Run only specific modular sections:

```bash
ENABLED_SECTIONS=open_play,defensive python fetch_football_data.py
```

---

## 9. Supabase Storage publishing

To upload generated artifacts to Supabase Storage:

```bash
UPLOAD_TO_SUPABASE_STORAGE=1
SUPABASE_S3_ENDPOINT=https://<project-ref>.storage.supabase.co/storage/v1/s3
SUPABASE_S3_BUCKET=your_bucket_name
SUPABASE_S3_ACCESS_KEY=...
SUPABASE_S3_SECRET_KEY=...
SUPABASE_S3_PREFIX=
SUPABASE_PUBLIC_BASE_URL=https://<project-ref>.supabase.co
```

Upload paths mirror the local `reports/` tree.

Example:

```text
reports/index.json
```

uploads to:

```text
<SUPABASE_S3_PREFIX>/reports/index.json
```

Re-uploading the same report path overwrites the existing object at that key.

---

## 10. GitHub Actions refresh

The scheduled workflow runs the pipeline automatically.

Typical command:

```bash
python fetch_football_data.py --force-refresh
```

The workflow needs the same environment variables as local runs, stored as GitHub repository secrets.

Important secrets:

```text
SUPABASE_FUNCTION_URL
SUPABASE_ANON_KEY
SUPABASE_S3_ENDPOINT
SUPABASE_S3_BUCKET
SUPABASE_S3_ACCESS_KEY
SUPABASE_S3_SECRET_KEY
SUPABASE_PUBLIC_BASE_URL
```

If the workflow fails with `Invalid JWT`, check that `SUPABASE_ANON_KEY` is the correct JWT-style Supabase anon key and not a malformed value or publishable key.

---

## 11. Refresh flow from Lovable

A browser refresh only reloads already-published JSON files. It does not recompute analytics from Wyscout.

A full refresh must run server-side:

```text
Lovable frontend
  -> Supabase refresh Edge Function
  -> refresh_runner.py
  -> python fetch_football_data.py --force-refresh
  -> reports updated
  -> frontend refetches reports/index.json
```

When a refresh succeeds, the frontend should refetch `reports/index.json` with a cache-busting query string and reload section JSON files.

---

## 12. Caching

### Event cache

Enabled by default:

```bash
ENABLE_INCREMENTAL_EVENT_FETCH=1
EVENT_CACHE_DIR=cache/events
EVENT_CACHE_RECHECK_MISSING_HOURS=24
```

Notes:

- event files are cached per match,
- `--force-refresh` bypasses the cache,
- set `ENABLE_INCREMENTAL_EVENT_FETCH=0` to always hit the API for events.

### Competition cache

Enabled by default:

```bash
ENABLE_INCREMENTAL_COMPETITION_FETCH=1
COMPETITION_CACHE_DIR=cache/competitions
COMPETITION_CACHE_TTL_HOURS=24
```

Notes:

- competition match responses are cached per competition,
- `--force-refresh` bypasses the cache,
- if a competition search does not resolve, no CSV is written for that export.

---

## 13. Branching and way of working

### `main`

`main` should always contain stable functionality that J-Södra can understand and use.

Rules:

- must run successfully,
- must keep the frontend contract stable,
- must not include unfinished experiments unless clearly hidden/disabled,
- must not include secrets.

### `dev`

`dev` is for active development.

Rules:

- new dashboard sections can be developed here,
- pull requests should usually target `dev` first,
- tested features can later be merged into `main`.

### Feature branches

Use clear branch names:

```text
feature/open-play-section
feature/throw-ins-analysis
feature/defensive-maps
fix/github-refresh-jwt
```

### Pull request checklist

Every pull request should explain:

- what changed,
- why it changed,
- how it was tested,
- which section or report files were affected,
- whether the frontend contract changed,
- screenshots if the dashboard changed,
- any new environment variables.

---

## 14. Where code should go

```text
fetch_football_data.py
  CLI only. Do not add feature logic.

pipeline/orchestrator.py
  Pipeline coordination only.

pipeline/registry.py
  List of enabled modular sections.

pipeline/context.py
  Shared PipelineContext passed to sections.

pipeline/contracts.py
  SectionResult and shared contracts.

pipeline/common.py
  General helpers: text normalisation, JSON-safe conversion, masks, IDs.

pipeline/analytics.py
  Reusable football calculations.

pipeline/data_service.py
  Wyscout/Supabase access and dataset collection.

pipeline/publishing.py
  JSON/CSV writing, refs, Supabase Storage upload.

pipeline/sections/*.py
  Section-specific analytics and section-specific outputs.

pipeline/visualisations/*.py or pipeline/plots.py
  Shared plotting helpers and mplsoccer pitch visualisations.
```

---

## 15. Current known dashboard sections

### Overview

General season context, match count, results, points, goals for, goals against.

### Recent form

Recent match results and form summary.

### Head-to-head

Previous meetings between J-Södra and the next opponent, when available.

### Corners

Corner attacking and defensive analysis, including CSV exports and plots.

### Open play

In progress. Should cover progression, entries, open-play shots, xG, and threat conceded.

### Free kicks

In progress. Should cover direct and indirect free-kick threat for and against.

### Throw-ins

In progress. Should cover throw-in retention, progression, zones, and shot creation.

### Defensive

In progress. Should cover defensive actions, pressing, recoveries, entries conceded, and shot/xG conceded.

---

## 16. Golden rule

If a collaborator is unsure where code belongs, use this rule:

> If it is specific to one dashboard tab, put it in that section file.  
> If multiple sections need it, move it to a shared helper module.  
> If it fetches data, it belongs in `DataService`.  
> If it writes/uploads files, it belongs in `publishing.py`.  
> If it draws a football pitch, use `mplsoccer` and the shared repo colours.
