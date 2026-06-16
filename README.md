# J-Södra Analytics

Football intelligence platform for Jönköpings Södra.

This repository contains the data pipeline and publishing contract used by the Lovable dashboard. The pipeline fetches football data through Supabase Edge Functions, builds analytics reports, creates visualisations, and publishes a modular `reports/` folder that the frontend can read.

---

## Table of Contents

1. [Project purpose](#1-project-purpose)
2. [Architecture overview](#2-architecture-overview)
3. [Repository structure](#3-repository-structure)
4. [Core design principles](#4-core-design-principles)
5. [Section folder pattern](#5-section-folder-pattern)
6. [Adding or changing a section](#6-adding-or-changing-a-section)
7. [Frontend output contract](#7-frontend-output-contract)
8. [Visual design and plotting rules](#8-visual-design-and-plotting-rules)
9. [Environment setup](#9-environment-setup)
10. [Running locally](#10-running-locally)
11. [Testing sections](#11-testing-sections)
12. [Supabase Storage publishing](#12-supabase-storage-publishing)
13. [GitHub Actions and refresh flow](#13-github-actions-and-refresh-flow)
14. [Supabase Edge Functions](#14-supabase-edge-functions)
15. [Caching](#15-caching)
16. [Branching and issue workflow](#16-branching-and-issue-workflow)
17. [Where code should go](#17-where-code-should-go)
18. [Current dashboard sections](#18-current-dashboard-sections)
19. [Golden rule](#19-golden-rule)

---

## 1. Project purpose

The goal is to give J-Södra a simple analytics hub for:

- understanding upcoming opponents,
- reviewing J-Södra's own performance,
- preparing match-specific insights,
- comparing team and opponent tendencies,
- publishing repeatable analytics to the Lovable frontend.

The system is designed so multiple collaborators can work on separate dashboard sections without editing the same large file.

---

## 2. Architecture overview

```text
GitHub Actions
  -> runs run_pipeline.py

run_pipeline.py
  -> small command-line entrypoint only
  -> parses arguments
  -> loads settings
  -> calls pipeline.orchestrator.run_pipeline(...)

pipeline/orchestrator.py
  -> coordinates shared data collection
  -> creates PipelineContext
  -> writes core reports
  -> runs registered section modules
  -> writes reports/index.json
  -> uploads generated artifacts when enabled

pipeline/sections/<section_name>/
  -> one dashboard section per folder
  -> section-specific metrics, plots, storylines, and publishing

pipeline/publishing.py
  -> writes JSON/CSV files
  -> builds frontend file references
  -> uploads artifacts to Supabase Storage

Lovable frontend
  -> reads reports/index.json
  -> follows section references from index.sections
```

A browser refresh only reloads already-published files. A real data refresh must run the server-side pipeline.

---

## 3. Repository structure

Recommended structure:

```text
.
├── run_pipeline.py
├── README.md
├── .env.example
├── requirements.txt
├── pipeline/
│   ├── __init__.py
│   ├── analytics.py
│   ├── common.py
│   ├── context.py
│   ├── contracts.py
│   ├── data_service.py
│   ├── orchestrator.py
│   ├── publishing.py
│   ├── registry.py
│   ├── section_runner.py
│   ├── settings.py
│   └── sections/
│       ├── __init__.py
│       ├── _helpers.py
│       ├── corners/
│       │   ├── __init__.py
│       │   ├── metrics.py
│       │   ├── plots.py
│       │   ├── section.py
│       │   └── storylines.py
│       ├── head_to_head/
│       │   ├── __init__.py
│       │   ├── plots.py
│       │   └── section.py
│       ├── open_play/
│       ├── free_kicks/
│       ├── throw_ins/
│       └── defensive/
├── reports/
│   └── index.json
├── supabase/
│   └── functions/
└── tools/
    └── smoke_test_section.py
```

`reports/` is generated output. Do not manually edit files in `reports/`; update the pipeline or section code and regenerate reports.

---

## 4. Core design principles

### 4.1 Keep the entrypoint small

`run_pipeline.py` must stay small.

It should only:

1. parse command-line arguments,
2. load settings,
3. call `pipeline.orchestrator.run_pipeline(...)`.

Do **not** add feature logic, Wyscout logic, plotting logic, or section-specific logic to `run_pipeline.py`.

### 4.2 Keep the orchestrator clean

`pipeline/orchestrator.py` should coordinate the pipeline only.

It may:

- resolve the target team,
- collect shared datasets,
- resolve the next opponent,
- build shared `PipelineContext`,
- write core reports,
- run registered sections,
- write `reports/index.json`,
- upload generated files.

It should not contain corner logic, open-play logic, defensive logic, plot implementation, or section-specific JSON contracts.

### 4.3 Data access belongs in `DataService`

All Wyscout/Supabase data access should go through:

```text
pipeline/data_service.py
```

Collaborators should normally not call Wyscout directly from a section file. Sections should use the shared datasets available through `PipelineContext`.

### 4.4 Publishing belongs in `publishing.py`

Sections write files locally, but they should not upload directly to Supabase Storage.

Normal flow:

1. section creates JSON/CSV/PNG files under `reports/<section_name>/`,
2. section returns a `SectionResult`,
3. orchestrator collects all generated files,
4. `pipeline/publishing.py` uploads files to Supabase Storage if upload is enabled.

---

## 5. Section folder pattern

All dashboard-specific football logic should live under:

```text
pipeline/sections/<section_name>/
```

A full section can use this structure:

```text
pipeline/sections/<section_name>/
  __init__.py      # exposes SECTION_NAME and build_section
  section.py       # publishes the section contract
  metrics.py       # calculates section-specific metrics
  plots.py         # creates section-specific visualisations
  storylines.py    # creates section-specific written insights
```

For a small section, it is fine to start with only:

```text
pipeline/sections/open_play/
  __init__.py
  section.py
```

Split into `metrics.py`, `plots.py`, and `storylines.py` when the file becomes hard to read.

### What should be self-contained?

A section should be self-contained as a dashboard feature, but it should not duplicate shared infrastructure.

Use this rule:

```text
Section-specific football logic        -> pipeline/sections/<section_name>/
Reusable football calculations         -> pipeline/analytics.py
General helper functions               -> pipeline/common.py
Wyscout/Supabase fetching              -> pipeline/data_service.py
Writing JSON/CSV and file references   -> pipeline/publishing.py
Pipeline coordination                  -> pipeline/orchestrator.py
Running enabled sections               -> pipeline/section_runner.py
```

---

## 6. Adding or changing a section

Every section package must expose:

```python
SECTION_NAME = "section_name"

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

- [ ] lives under `pipeline/sections/<section_name>/`,
- [ ] has a clear `SECTION_NAME`,
- [ ] implements `build_section(context)`,
- [ ] uses the shared `PipelineContext`,
- [ ] writes files only under `reports/<section_name>/`,
- [ ] returns all generated files in `SectionResult.files`,
- [ ] adds frontend references through `SectionResult.index_entry`,
- [ ] uses `pipeline/publishing.py` helpers for JSON/CSV and refs,
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

## 7. Frontend output contract

The Lovable frontend should start by loading:

```text
reports/index.json
```

The frontend should then read the `sections` object and fetch the files listed there.

Do not rely on old root-level payload files.

Expected report tree:

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
      goal_diff_recent.png
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

Example `reports/index.json` section reference:

```json
{
  "sections": {
    "corners": {
      "analysis": {
        "path": "reports/corners/analysis.json",
        "url": "https://..."
      }
    },
    "head_to_head": {
      "overview": {
        "path": "reports/head_to_head/overview.json",
        "url": "https://..."
      }
    }
  }
}
```

---

## 8. Visual design and plotting rules

The dashboard should look and feel like one product. All sections must follow the same club-inspired visual language.

### 8.1 Required colour palette

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

### 8.2 Use `mplsoccer` for football pitch plots

Use `mplsoccer` as much as possible for pitch-based football visualisations.

Examples:

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

### 8.3 Plot file rules

Plots should be written under:

```text
reports/<section_name>/plots/
```

Data exports should be written under:

```text
reports/<section_name>/data/
```

The section should include plot/data references in its `analysis.json` or section payload.

---

## 9. Environment setup

Create a local `.env` file from the example file:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Fill in the required Supabase/Wyscout values.

Never commit `.env`. Only `.env.example` should be committed.

Important local variables:

```env
SUPABASE_FUNCTION_URL=https://<project-ref>.supabase.co/functions/v1/wyscout-proxy
SUPABASE_ANON_KEY=your_supabase_anon_key
OUTPUT_DIR=.
REPORTS_DIR=reports
```

For Supabase Storage upload:

```env
UPLOAD_TO_SUPABASE_STORAGE=1
SUPABASE_S3_ENDPOINT=https://<project-ref>.storage.supabase.co/storage/v1/s3
SUPABASE_S3_BUCKET=your_bucket_name
SUPABASE_S3_ACCESS_KEY=your_s3_access_key
SUPABASE_S3_SECRET_KEY=your_s3_secret_key
SUPABASE_PUBLIC_BASE_URL=https://<project-ref>.supabase.co
```

---

## 10. Running locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the pipeline:

```bash
python run_pipeline.py
```

Force a full upstream refresh:

```bash
python run_pipeline.py --force-refresh
```

Run only specific modular sections.

Bash/macOS/Linux:

```bash
ENABLED_SECTIONS=corners,head_to_head python run_pipeline.py
```

PowerShell:

```powershell
$env:ENABLED_SECTIONS="corners,head_to_head"
python .\run_pipeline.py
Remove-Item Env:\ENABLED_SECTIONS
```

PowerShell one-liner:

```powershell
$env:ENABLED_SECTIONS="corners,head_to_head"; python .\run_pipeline.py; Remove-Item Env:\ENABLED_SECTIONS
```

---

## 11. Testing sections

### 11.1 Compile checks

Run this before pushing changes:

```bash
python -m py_compile run_pipeline.py pipeline/orchestrator.py pipeline/registry.py pipeline/section_runner.py
```

Compile a specific section:

```bash
python -m py_compile pipeline/sections/corners/section.py pipeline/sections/corners/metrics.py pipeline/sections/corners/plots.py pipeline/sections/corners/storylines.py
```

### 11.2 Smoke-test a section without fetching Wyscout

The smoke test does not fetch Wyscout data. It creates an empty `PipelineContext` and runs one section.

```bash
python tools/smoke_test_section.py corners
python tools/smoke_test_section.py head_to_head
```

This checks:

- imports,
- section wiring,
- JSON writing,
- `SectionResult` output,
- basic report contract shape.

### 11.3 Run one section with real pipeline data

PowerShell:

```powershell
$env:ENABLED_SECTIONS="corners"
python .\run_pipeline.py
Remove-Item Env:\ENABLED_SECTIONS
```

Then check:

```text
reports/index.json
reports/corners/analysis.json
reports/corners/data/
reports/corners/plots/
```

### 11.4 Check `reports/index.json`

PowerShell-safe command:

```powershell
@'
import json
from pathlib import Path

index = json.loads(Path("reports/index.json").read_text(encoding="utf-8"))
print(index["sections"].keys())
print(index["sections"].get("corners"))
print(index["sections"].get("head_to_head"))
'@ | python -
```

---

## 12. Supabase Storage publishing

To upload generated artifacts to Supabase Storage:

```env
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

## 13. GitHub Actions and refresh flow

The scheduled workflow runs the pipeline automatically.

Typical command:

```bash
python run_pipeline.py --force-refresh
```

The workflow needs the same environment variables as local runs, stored as GitHub repository secrets.

Important GitHub Actions secrets:

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

## 14. Supabase Edge Functions

### 14.1 `refresh-reports`

Preferred manual refresh flow:

```text
Lovable Refresh button
  -> Supabase Edge Function refresh-reports
  -> GitHub Actions workflow_dispatch
  -> python run_pipeline.py --force-refresh
  -> reports uploaded to Supabase Storage
  -> Lovable polls refresh status
  -> Lovable reloads reports/index.json
```

This function keeps the GitHub token server-side. The frontend should never store or expose the GitHub token.

Required Supabase Edge Function secrets:

```text
GITHUB_OWNER
GITHUB_REPO
GITHUB_TOKEN
GITHUB_REFRESH_WORKFLOW_FILE
GITHUB_REFRESH_REF
```

The GitHub workflow must support `workflow_dispatch`.

### 14.2 `sync-league`

`sync-league` is a warehouse sync function.

Purpose:

```text
Wyscout -> Supabase Edge Function -> Supabase warehouse tables
```

It syncs league, season, team, match, event, and team-match-stat data into the Supabase database. It does not generate the `reports/` folder and does not upload report JSON/PNG/CSV files to Supabase Storage.

Typical required Supabase secrets:

```text
WYSCOUT_CLIENT_ID
WYSCOUT_CLIENT_SECRET
WYSCOUT_BASE_URL
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SYNC_LEAGUE_TOKEN
```

Use `sync-league` when the Supabase warehouse/RPC flow is needed. Use `run_pipeline.py` when generating Lovable report files.

---

## 15. Caching

### 15.1 Event cache

Enabled by default:

```env
ENABLE_INCREMENTAL_EVENT_FETCH=1
EVENT_CACHE_DIR=cache/events
EVENT_CACHE_RECHECK_MISSING_HOURS=24
```

Notes:

- event files are cached per match,
- `--force-refresh` bypasses the cache,
- set `ENABLE_INCREMENTAL_EVENT_FETCH=0` to always hit the API for events.

### 15.2 Competition cache

Enabled by default:

```env
ENABLE_INCREMENTAL_COMPETITION_FETCH=1
COMPETITION_CACHE_DIR=cache/competitions
COMPETITION_CACHE_TTL_HOURS=24
```

Notes:

- competition match responses are cached per competition,
- `--force-refresh` bypasses the cache,
- if a competition search does not resolve, no CSV is written for that export.

---

## 16. Branching and issue workflow

### 16.1 Branches

`main` should always contain stable functionality that J-Södra can understand and use.

Rules for `main`:

- must run successfully,
- must keep the frontend contract stable,
- must not include unfinished experiments unless clearly hidden/disabled,
- must not include secrets.

`dev` is for active development.

Rules for `dev`:

- new dashboard sections can be developed here,
- pull requests should usually target `dev` first,
- tested features can later be merged into `main`.

Use clear feature branch names:

```text
feature/open-play-section
feature/throw-ins-analysis
feature/defensive-maps
fix/github-refresh-jwt
```

### 16.2 Issue workflow

All work should be connected to an issue. The state of each issue is tracked in the Kanban board under the Projects tab.

Issue states:

```text
Backlog -> Ready -> In Progress -> In Review -> Done
```

When starting work:

- assign the issue to yourself,
- move the issue to `In Progress`,
- create a dedicated branch.

When work is finished:

- open a pull request,
- move the issue to `In Review`,
- ask at least one collaborator to review.

### 16.3 Pull request checklist

Every pull request should explain:

- what changed,
- why it changed,
- how it was tested,
- which section or report files were affected,
- whether the frontend contract changed,
- screenshots if the dashboard changed,
- any new environment variables.

---

## 17. Where code should go

```text
run_pipeline.py
  CLI only. Do not add feature logic.

pipeline/orchestrator.py
  Pipeline coordination only.

pipeline/registry.py
  List of enabled modular sections.

pipeline/section_runner.py
  Shared helper for running registered sections.

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

pipeline/sections/<section_name>/section.py
  Section publishing contract.

pipeline/sections/<section_name>/metrics.py
  Section-specific calculations.

pipeline/sections/<section_name>/plots.py
  Section-specific visualisations.

pipeline/sections/<section_name>/storylines.py
  Section-specific written insights.

pipeline/plots.py
  Deprecated compatibility wrapper only. Do not add new plots here.
```

---

## 18. Current dashboard sections

### Overview

General season context, match count, results, points, goals for, goals against.

### Recent form

Recent match results and form summary.

### Head-to-head

Previous meetings between J-Södra and the next opponent, including optional recent H2H goal-difference plot.

### Corners

Corner attacking and defensive analysis, including CSV exports, plots, and storylines.

Current Corners section structure:

```text
pipeline/sections/corners/
  metrics.py      # calculations
  plots.py        # visualisations
  section.py      # published JSON/CSV/PNG contract
  storylines.py   # text insights
```

### Open play

In progress. Should cover progression, entries, open-play shots, xG, and threat conceded.

### Free kicks

In progress. Should cover direct and indirect free-kick threat for and against.

### Throw-ins

In progress. Should cover throw-in retention, progression, zones, and shot creation.

### Defensive

In progress. Should cover defensive actions, pressing, recoveries, entries conceded, and shot/xG conceded.

---

## 19. Golden rule

If a collaborator is unsure where code belongs, use this rule:

> If it is specific to one dashboard tab, put it in that section folder.  
> If multiple sections need it, move it to a shared helper module.  
> If it fetches data, it belongs in `DataService`.  
> If it writes or uploads files, it belongs in `publishing.py`.  
> If it coordinates the pipeline, it belongs in `orchestrator.py`.  
> If it draws a football pitch, use `mplsoccer` and the shared repo colours.
