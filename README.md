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
