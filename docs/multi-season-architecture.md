# Multi-Season Analytics Architecture

## Goals

- Keep current-season data strictly inside the current season.
- Keep previous seasons isolated and queryable without cross-season mixing.
- Sync leagues incrementally with upserts only.
- Make every team in a synced league available automatically.
- Preserve the current `reports/` pipeline and storage objects while the new warehouse is introduced.

## Schema Proposal

### Core lookup tables

- `public.leagues`
  - One row per provider league.
  - `unique (provider, provider_league_id)` keeps the Wyscout id stable.
  - `is_active` supports hiding old competitions without deleting history.

- `public.seasons`
  - One row per provider season.
  - `league_id` isolates every season under exactly one league.
  - `is_current` is per-league state, not a global flag across the whole warehouse.
  - `unique (provider, provider_season_id)` prevents cross-season overwrites.

- `public.teams`
  - One row per provider team.
  - Team identity is stable even if the team is promoted or relegated.

- `public.season_teams`
  - Join table between `seasons` and `teams`.
  - This is the key to promoted and relegated teams. A team does not need to stay in the same league across seasons.

### Match and event facts

- `public.matches`
  - Season-aware match fact table.
  - `league_id` and `season_id` are stored directly for fast filtering.
  - `provider_match_id` is unique per provider so ingestion can upsert safely.
  - `home_team_id` and `away_team_id` are nullable to allow summary-first bootstraps before detail hydration.

- `public.team_match_stats`
  - One row per team per match.
  - This is the canonical table for rolling analytics, home/away splits, match-range filters, and season compare.
  - The table denormalizes `match_kickoff_at`, `match_status`, `venue`, and `round_number` so the frontend queries do not need heavy joins.
  - `xg_*`, `xp`, and `xt_*` are nullable because the data source or model may not exist yet. That avoids fake zeros.

- `public.events`
  - Event store keyed by provider event id.
  - Needed for advanced recomputation, future plot generation, xT models, and auditability.

### Precomputed analytics tables

- `public.standings`
  - Season-scoped table position cache.
  - `snapshot_key` defaults to `current` and leaves room for future historical standings snapshots.

- `public.aggregated_team_stats`
  - Precomputed common scopes for fast UI reads.
  - Current implementation writes four scopes per team and season:
    - `season_full`
    - `venue_home`
    - `venue_away`
    - `last_5`
  - This is intentionally a table instead of a SQL materialized view because selective season recompute is cheaper and easier to control after every sync.

### Sync state tables

- `public.sync_runs`
  - Audit log for hosted sync runs.
  - Useful for cron observability and debugging partial syncs.

- `public.sync_cursors`
  - Optional cursor storage for future delta APIs or provider `updated_after` support.
  - The current function does summary comparison plus targeted hydration, but the table is there for the next step.

## Migration Strategy From Current Data

### What gets migrated now

- Existing flat `reports/` files remain where they are.
- Existing uploaded plots remain where they are.
- The new warehouse starts as an additive layer in Supabase.
- The current pipeline does not need to read from the new warehouse on day one.

### How to bootstrap safely

1. Run the new migrations.
2. Deploy the `sync-league` edge function with JWT verification disabled.
3. Run one bootstrap sync per league with `include_events=true`.
4. Verify `season_teams`, `matches`, `team_match_stats`, `standings`, and `aggregated_team_stats` for the current season.
5. Run the same sync again for the previous season you want to expose.
6. Only after the data is correct, point the new frontend explorer to the RPC functions.
7. Keep the current `reports/index.json` flow as the default production route until the new explorer is stable.

`sync-league` authenticates inside the function with `SYNC_LEAGUE_TOKEN`, so the Supabase gateway must not require a JWT for that function.

### Why this avoids data loss

- All warehouse writes are inserts or upserts keyed by provider ids.
- Nothing in the new flow deletes another season.
- Nothing in the new flow touches the current storage bucket objects.
- Existing report generation and uploads stay on their current contract.

## Incremental Update Algorithm

### Current algorithm implemented in `sync-league`

1. Fetch competition match summaries for the target league.
2. Filter to the requested season ids if provided.
3. Upsert league and season rows.
4. Compare summary rows with already stored `matches` rows.
5. Hydrate only matches that are new, missing team ids, recently scheduled, or whose score/status changed.
6. Fetch team profiles only for teams found in hydrated match details.
7. Upsert `teams`, `season_teams`, and `matches`.
8. For final matches only:
   - fetch events
   - rebuild `team_match_stats` for that match
   - rebuild `events` for that match
9. Recompute `standings` and `aggregated_team_stats` only for affected seasons.
10. Record the hosted run in `sync_runs`.

### Why this is season-safe

- Every write carries `season_id` and `league_id`.
- Recompute is called per season, not globally.
- Current season queries never need to join previous seasons unless the caller explicitly asks for them.

### What not to do

- Do not truncate `matches`, `team_match_stats`, or `events` during regular syncs.
- Do not use a global `current season` cache without league scope.
- Do not write team aggregates without a `season_id`.

## What To Recompute Live vs On Schedule

### Recompute immediately after every sync

- `standings`
- `aggregated_team_stats` for `season_full`, `venue_home`, `venue_away`, and `last_5`
- `api_dashboard_context` consumers, because they depend on those season caches

### Recompute on schedule or after a complete matchday

- xT model outputs if you adopt a possession-chain model
- xP model outputs once you define the model you trust
- expensive plot regeneration for all teams
- cross-season benchmarking tables or league-wide percentile ranks

### Recommendation

- Use live recompute for small season-level aggregates.
- Use hourly or post-matchday jobs for heavier model-based features.
- Treat xP and xT as model-versioned outputs, not as simple raw-provider facts.

## Query Layer

### Implemented RPCs and views

- `public.api_filter_options(league_id, season_id)`
  - League, season, and team selector data.

- `public.api_dashboard_context(season_id, team_id)`
  - Default next-match header, latest match, standing, season-full metrics, and last-five metrics.

- `public.api_standings(season_id, snapshot_key, team_id)`
  - Table view for the selected season, optionally scoped to the selected team's subgroup.

- `public.api_team_matches(season_id, team_id, venue_filter, limit, offset)`
  - Match list for sliders, tabs, and recent-form sections.

- `public.api_team_metrics(season_id, team_id, venue_filter, match_limit)`
  - Dynamic window metrics for match-range slider use.

- `public.api_compare_team_seasons(team_id, season_ids[])`
  - Season-vs-season comparison cards and charts.

- `public.v_team_season_options`
  - Flat selector view.

- `public.v_matches_flat`
  - Flattened match card view.

### Why I used cached tables instead of SQL materialized views

- Season-scoped refreshes are easier to target with tables.
- You can recompute one season without refreshing a whole league-wide materialized view.
- This avoids locking or heavy refresh cycles on every sync.

### If you later want SQL materialized views

- Add them as read-only wrappers, not as the source of truth.
- Recommended candidates:
  - `mv_current_standings_public`
  - `mv_team_scope_cards_public`
  - `mv_league_rank_percentiles_public`

## Frontend Redesign Plan

### Default behavior to preserve

- Keep the existing next-match dashboard flow as the default entry point.
- When the user does nothing, load:
  - the current league
  - the current season in that league
  - the configured default team
  - the next-match context for that team

### New filters

- League selector
- Season selector
- Team selector
- Match-range selector or slider
- Venue split selector: `all`, `home`, `away`

### UI states

- `default mode`
  - Uses `api_dashboard_context`.
  - Looks and behaves like the current next-match dashboard.

- `explorer mode`
  - Uses `api_team_metrics`, `api_team_matches`, `api_standings`, and `api_compare_team_seasons`.
  - Works for any team and any synced season.

### Frontend rules

- Never hardcode team names.
- Never hardcode season ids.
- Never derive the available teams outside `season_teams`.
- Make season changes reset team choices only when the selected team is not present in the new season.
- When xP or xT is null, show `Unavailable` instead of `0.00`.

## Edge Function and Cron Architecture

### Implemented hosted pieces

- `supabase/functions/sync-league/index.ts`
  - Hosted league sync and season recompute entry point.

- `.github/workflows/sync-league.yml`
  - Hosted scheduler that calls the edge function every hour.

### Suggested responsibility split

- Edge function:
  - fetch upstream data
  - upsert season-aware warehouse rows
  - trigger season recompute

- GitHub Actions schedule:
  - recurring trigger
  - manual backfill trigger with custom payload

- Existing `refresh-reports` flow:
  - keep current report JSON and plot publication working
  - do not merge it into the new sync until the warehouse is stable

## Keeping Current Reports and Plots Working

### Rule

- Do not replace the current `reports/` tree while introducing the warehouse.

### Practical rollout strategy

1. Leave `fetch_football_data.py` unchanged for the current app.
2. Build the new UI against Supabase RPCs in parallel.
3. When you want DB-backed plots later, publish them into a namespaced path such as:
   - `reports/v2/{league_provider_id}/{season_provider_id}/{team_provider_id}/...`
4. Never delete storage keys outside the namespace being actively regenerated.
5. Do not reuse old static paths for new multi-team dynamic assets.

## Step-by-Step Rollout Plan

1. Apply the new migrations in Supabase.
2. Deploy `sync-league` with service role and Wyscout credentials, and disable JWT verification for that function.
3. Add the scheduled GitHub workflow secrets.
4. Run one manual bootstrap for the current season.
5. Validate selectors, standings, and team counts.
6. Run one bootstrap for the previous season.
7. Build the new frontend explorer against the RPC layer.
8. Keep the existing storage dashboard live as the default route.
9. Add xP and xT models only after the warehouse and explorer are trusted.
10. If you later move plot generation into the warehouse flow, publish into a versioned namespace only.

If you deploy from the Supabase dashboard, turn off JWT verification for `sync-league` before testing it. If you deploy from the CLI later, use `supabase functions deploy sync-league --no-verify-jwt`.

## Pitfalls

### Season boundaries

- Do not infer season membership from kickoff year alone.
- Always trust provider `seasonId` first.

### Promoted and relegated teams

- A team can exist in multiple leagues across seasons.
- That is why `season_teams` exists and why `teams` does not carry a single permanent league binding.

### Cache invalidation

- Match summaries can change close to kickoff and after final whistle.
- Rehydrate recent matches and all changed scores or statuses.

### Old plots

- Do not delete old storage keys during warehouse sync.
- Use append-only or namespaced publish paths for any future multi-team plot generation.

### xP and xT accuracy

- Do not invent xP from points.
- Do not publish xT until the model and the refresh cadence are defined.
- Null is safer than a fake value.
