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
