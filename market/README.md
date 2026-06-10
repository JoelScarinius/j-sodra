# Market Assets

This folder is intentionally separate from the main report pipeline.

- It does not write into `reports/`.
- It does not upload anything to Supabase Storage.
- It keeps the Wyscout integration isolated in `market/data.py`, so the package is easy to extract later.

## What it generates

- `progressive_pass_pulse.png`: accurate open-play progressive passes for the current team and season.
- `defensive_footprint.png`: defensive action heatmap with finer pitch bins and regain markers.
- `dropped_possessions.png`: long-possession failed passes that turn into quick opponent pickups.
- `latest_match_pass_network.png`: trimmed pass network for the latest played match.
- `season_shot_map.png`: current-season shot map sized by xG.
- `standout_player_radar.png`: player radar based on event-derived per-match metrics.
- `manifest.json`: metadata describing the generated files.

## Usage

From the repo root, use the project virtual environment:

```bash
../.venv/bin/python -m market.generate_marketing_plots
```

Optional overrides:

```bash
../.venv/bin/python -m market.generate_marketing_plots --team-id 1619 --season-id 192451 --player "A. Player"
```

Useful flags:

- `--output-dir market/output`
- `--max-matches 8`
- `--force-refresh`

The generator reuses the existing Supabase edge-function configuration from `.env` through `pipeline.settings` and `pipeline.data_service`.

By default, when no explicit `--season-id` is provided, the generator keeps only matches from the current calendar year inside the active season slice. For the current project this means the default output is restricted to the 2026 season data.