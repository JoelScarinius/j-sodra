# J-Sodra Analytics Pipeline

This pipeline pulls Wyscout data through the Supabase proxy, computes season-scoped overview, recent form, H2H, and corner analysis, generates corner and H2H visuals, and publishes a modular `reports/` tree for the Lovable frontend.

Open-play logic is intentionally removed from the current version.

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Required env vars

Set these in local `.env` and do not commit secrets:

```env
SUPABASE_FUNCTION_URL=https://ytzuftamjgafzgyogpke.supabase.co/functions/v1/wyscout-proxy
SUPABASE_ANON_KEY=your_supabase_anon_key
```

Supabase edge function secrets for the Wyscout proxy:

```env
WYSCOUT_CLIENT_ID=...
WYSCOUT_CLIENT_SECRET=...
WYSCOUT_BASE_URL=https://apirest.wyscout.com/v3
```

Common pipeline controls:

```env
FILTER_TO_ACTIVE_SEASON=1
ENABLE_PREVIOUS_SEASON_COMPLEMENT=0
H2H_FALLBACK_TO_PREVIOUS_SEASON=1
OUTPUT_DIR=.
REPORTS_DIR=reports
```

## 3. Run pipeline

Primary entrypoint:

```bash
python fetch_football_data.py
```

Force a full refresh from the upstream API and bypass local caches:

```bash
python fetch_football_data.py --force-refresh
```

## 4. Published output contract

The pipeline writes a modular `reports/` tree instead of one large JSON payload:

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
  context/
    season.json
    analysis.json
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
      team_offensive.csv
      team_defensive.csv
      next_opponent_offensive.csv
      next_opponent_defensive.csv
    plots/
      team_offensive_map.png
      team_defensive_map.png
      team_target_map.png
      team_danger_end_heatmap.png
      team_taker_impact.png
      team_xg_method_comparison.png
      team_shooter_impact.png
      next_opponent_offensive_map.png
      next_opponent_defensive_map.png
      next_opponent_target_map.png
      next_opponent_danger_end_heatmap.png
      next_opponent_taker_impact.png
      next_opponent_xg_method_comparison.png
      next_opponent_shooter_impact.png
  exports/
    competitions/
      division1_matches.csv
  upload_manifest.json
```

Notes:

- `reports/index.json` is the frontend bootstrap file.
- Each JSON section contains only its own domain data plus file references.
- Legacy root-level outputs have been removed. The current pipeline writes only under `reports/` plus `cache/`.
- Open-play payloads and shot maps are no longer generated.

## 5. Optional upload to Supabase Storage

```env
UPLOAD_TO_SUPABASE_STORAGE=1
SUPABASE_S3_ENDPOINT=https://ytzuftamjgafzgyogpke.storage.supabase.co/storage/v1/s3
SUPABASE_S3_BUCKET=your_bucket_name
SUPABASE_S3_ACCESS_KEY=...
SUPABASE_S3_SECRET_KEY=...
SUPABASE_S3_PREFIX=
SUPABASE_PUBLIC_BASE_URL=https://ytzuftamjgafzgyogpke.supabase.co
```

Notes:

- Upload paths mirror the local `reports/` tree exactly.
- Example: `reports/index.json` uploads to `<SUPABASE_S3_PREFIX>/reports/index.json`.
- Re-uploading the same report path overwrites the existing object at that exact key.
- `reports/upload_manifest.json` is written locally after upload and lists uploaded keys and public URLs.

## 6. Refresh webhook and runner

Lovable cannot trigger a real full refresh by refetching Storage alone. A server-side process has to run the pipeline.

This repo now includes two pieces for that flow:

- `refresh_runner.py`: a small Python HTTP service that runs `python fetch_football_data.py --force-refresh` and exposes run status.
- `supabase/functions/refresh-reports/index.ts`: a Supabase Edge Function that forwards browser requests to the runner using a server-side secret.

Run the refresh runner on the machine that has the repo, Python env, and file-system access:

```bash
python refresh_runner.py
```

Runner env vars:

```env
PIPELINE_REFRESH_RUNNER_HOST=0.0.0.0
PIPELINE_REFRESH_RUNNER_PORT=8080
PIPELINE_REFRESH_RUNNER_SECRET=choose_a_long_random_secret
```

Supabase function secrets for the webhook adapter:

```env
PIPELINE_REFRESH_RUNNER_URL=https://your-runner-host.example.com
PIPELINE_REFRESH_RUNNER_SECRET=choose_a_long_random_secret
```

Deploy the webhook adapter:

```bash
supabase functions deploy refresh-reports
```

Flow:

- `POST /functions/v1/refresh-reports` starts or reuses a refresh run.
- `GET /functions/v1/refresh-reports?run_id=<run_id>` returns run status.
- When the run returns `succeeded`, the frontend should refetch `reports/index.json` with a cache-busting query parameter and reload section JSONs.

`reports/index.json` now includes refresh metadata with `webhook_url`, `status_url_template`, and `poll_interval_ms` so the frontend does not need to hardcode the webhook path.

## 7. Incremental event fetching

Local event caching is enabled by default:

```env
ENABLE_INCREMENTAL_EVENT_FETCH=1
EVENT_CACHE_DIR=cache/events
EVENT_CACHE_RECHECK_MISSING_HOURS=24
```

Notes:

- Cached event files are stored per match under `OUTPUT_DIR/cache/events` by default.
- If a match temporarily has no statistical event data, the cache waits `EVENT_CACHE_RECHECK_MISSING_HOURS` before retrying that match.
- `--force-refresh` bypasses this cache for the run.
- Set `ENABLE_INCREMENTAL_EVENT_FETCH=0` to always hit the API for events.

## 8. Incremental competition exports

Competition snapshot caching is also enabled by default:

```env
ENABLE_INCREMENTAL_COMPETITION_FETCH=1
COMPETITION_CACHE_DIR=cache/competitions
COMPETITION_CACHE_TTL_HOURS=24
```

Notes:

- Cached competition responses are stored per competition under `OUTPUT_DIR/cache/competitions`.
- While cache is fresh, exports reuse cache and skip upstream competition-match API calls.
- After `COMPETITION_CACHE_TTL_HOURS`, the pipeline refreshes from API and rewrites cache.
- `--force-refresh` bypasses this cache for the run.
- If a competition search does not resolve, no CSV is written for that export.

## 9. Lovable handoff text

Send the full content of `lovable_message.txt` to Lovable.

# Way of working

- Gather function calls in fetch_football.py and decouple code.
- Kanban board backlog
- Description of how and what has been done and link to pull request.
- Main branch always updated with standard things J-Södra understands and uses.
- Dev branch with new things which we develope towards.
- Flow chart flow.

# Current Repo Notes

## Entrypoint And Contract

- The only pipeline entrypoint is `fetch_football_data.py`.
- The frontend contract is modular under `reports/`.
- Lovable must bootstrap from `reports/index.json`, then fetch section JSONs from `index.sections`.
- `lovable_dashboard_payload.json` is obsolete and should not be used.

## Corner Storyline Fields

- Lovable should render corner storyline text from `reports/corners/analysis.json`.
- Team storyline fields: `corners.team.offensive.storylines`, `corners.team.defensive.storylines`, `corners.storylines.team_offensive_success_factors`.
- Next-opponent storyline fields: `corners.next_opponent.offensive.storylines`, `corners.next_opponent.defensive.storylines`, `corners.storylines.next_opponent_offensive_success_factors`.

## Plot Colors

- Palette is defined in `pipeline/settings.py`: bg `#002418`, line `#f5f0da`, accent `#d4af37`, accent_2 `#6fcf97`, muted `#8ad6b4`, danger `#f07167`, text `#f5f0da`.
- Corner heatmap uses Matplotlib colormap `YlOrBr`.
- Corner danger heatmap uses `YlOrRd`.

## Refresh Flow

- A full refresh requires `python fetch_football_data.py --force-refresh` on the server side.
- The callable refresh path is browser -> `supabase/functions/refresh-reports` -> `refresh_runner.py` -> `fetch_football_data.py --force-refresh`.
- The frontend should poll the returned `run_id` until status is `succeeded`, then refetch `reports/index.json`.

## Incremental Caching

- Local event cache lives under `cache/events`.
- Competition cache lives under `cache/competitions`.
- `--force-refresh` bypasses both caches for the run.

## Adding a new analytics section

Analytics features are added as section modules under `pipeline/sections/`.

A section is responsible for one dashboard area, for example:

- `overview`
- `corners`
- `open_play`
- `free_kicks`
- `throw_ins`
- `defensive`

### Rules

1. Do not add feature logic to `fetch_football_data.py`.
2. Do not add feature logic directly to `pipeline/orchestrator.py`.
3. Create or edit a file in `pipeline/sections/`.
4. Use the shared `PipelineContext`.
5. Write outputs only under `reports/<section_name>/`.
6. Return a `SectionResult`.
7. Register the section in `pipeline/registry.py`.
8. Use `pipeline/common.py` and `pipeline/analytics.py` for shared helpers.
9. Use `pipeline/publishing.py` for writing JSON/CSV references.
10. Use `mplsoccer` as much as possible for pitch-based football visualisations.

### Example

Create:

```text

pipeline/sections/open_play.py
```

---

# Suggested section template

This is the kind of file collaborators should copy.

```python
from __future__ import annotations

from pipeline.contracts import SectionResult
from pipeline.publishing import build_ref, write_json


SECTION_NAME = "open_play"


def build_section(context) -> SectionResult:
    """
    Build the Open Play section.

    This section should only contain open-play specific logic.
    Shared helpers should live in pipeline/common.py or pipeline/analytics.py.
    Data fetching should be done through DataService before this section runs.
    """

    output_path = context.settings.report_path(SECTION_NAME, "analysis.json")

    payload = {
        "generated_at": context.generated_at,
        "team": {
            "summary": {},
            "metrics": [],
            "storylines": [],
        },
        "next_opponent": {
            "summary": {},
            "metrics": [],
            "storylines": [],
        },
        "files": {
            "plots": {},
            "data": {},
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
---

GitHub Actions

  runs fetch_football_data.py

fetch_football_data.py

  parses CLI only

pipeline/orchestrator.py

  builds shared context

  runs registered sections

  writes index.json

  uploads all artifacts

pipeline/sections/*.py

  each collaborator owns one section

pipeline/publishing.py

  uploads everything to Supabase Storage

  follows section refs

Lovable

  reads reports/index.json



Yes. Below is a **collaboration-ready plugin layer** you can add to the project.

The design is:

1. `fetch_football_data.py` stays tiny.
2. `pipeline/orchestrator.py` owns the main pipeline.
3. Collaborators add one file under `pipeline/sections/`.
4. Each section writes files under `reports/<section_name>/`.
5. Each section returns a `SectionResult`.
6. The orchestrator automatically adds the section to `reports/index.json`.
7. The existing Supabase upload logic uploads the section artifacts together with everything else.

This fits your existing architecture because `DataService` already owns Wyscout/Supabase fetching and caching, while `publishing.py` already owns JSON/CSV writing, public refs, and Supabase Storage uploads. [\[jonkopingu...epoint.com\]](https://jonkopinguniversity-my.sharepoint.com/personal/anjo19go_student_ju_se/Documents/Microsoft%20Copilot%20Chat%20Files/data_service.py), [\[jonkopingu...epoint.com\]](https://jonkopinguniversity-my.sharepoint.com/personal/anjo19go_student_ju_se/Documents/Microsoft%20Copilot%20Chat%20Files/publishing.py)

***

# 1. `fetch_football_data.py`

Replace the root entrypoint with this:

```python
"""Command-line entrypoint for the J-Södra analytics pipeline.

This file should stay intentionally small.

Do not add feature logic here.
Do not add Wyscout logic here.
Do not add plotting logic here.

The job of this file is only to:

1. Parse command-line arguments.
2. Load settings.
3. Start the pipeline orchestrator.
"""

from __future__ import annotations

import argparse

from pipeline.orchestrator import run_pipeline
from pipeline.settings import load_settings


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch and publish J-Södra football analytics."
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass local caches and fetch fresh data from the Wyscout API.",
    )

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_settings(force_refresh=args.force_refresh)
    return run_pipeline(settings)


if __name__ == "__main__":
    raise SystemExit(main())
```

---


````markdown
## Adding a new analytics section

Analytics features are added as modular section files under:

```text
pipeline/sections/
````

Each section owns one dashboard area.

Examples:

```text
pipeline/sections/open_play.py
pipeline/sections/free_kicks.py
pipeline/sections/throw_ins.py
pipeline/sections/defensive.py
```

### Rules for contributors

1. Do not add feature logic to `fetch_football_data.py`.
2. Do not add feature logic directly to `pipeline/orchestrator.py`.
3. Create or edit one section file under `pipeline/sections/`.
4. Use the shared `PipelineContext`.
5. Write outputs only under `reports/<section_name>/`.
6. Return a `SectionResult`.
7. Register the section in `pipeline/registry.py`.
8. Do not upload directly to Supabase Storage from a section.
9. Use `pipeline/publishing.py` to write JSON/CSV files.
10. Use `mplsoccer` as much as possible for football pitch visualisations.

### Section contract

Every section must implement:

```python
def build_section(context) -> SectionResult:
    ...
```

The section must return:

```python
SectionResult(
    name="section_name",
    files=[...],
    index_entry={...},
)
```

### How publishing works

A section writes local files under:

```text
reports/<section_name>/
```

The orchestrator collects all files from every section and uploads them to Supabase Storage when:

```bash
UPLOAD_TO_SUPABASE_STORAGE=1
```

The frontend should discover section files through:

```text
reports/index.json
```

The frontend should not hardcode paths where possible.

````

---

# 14. What collaborators will see in `reports/index.json`

After this is integrated, the generated `reports/index.json` will contain extra sections like:

```json
{
  "sections": {
    "open_play": {
      "analysis": {
        "path": "reports/open_play/analysis.json",
        "url": "https://..."
      }
    },
    "free_kicks": {
      "analysis": {
        "path": "reports/free_kicks/analysis.json",
        "url": "https://..."
      }
    },
    "throw_ins": {
      "analysis": {
        "path": "reports/throw_ins/analysis.json",
        "url": "https://..."
      }
    },
    "defensive": {
      "analysis": {
        "path": "reports/defensive/analysis.json",
        "url": "https://..."
      }
    }
  }
}
````

The Lovable frontend can then safely show the tabs, even while sections are still marked as:

```json
"status": "in_progress"
```
