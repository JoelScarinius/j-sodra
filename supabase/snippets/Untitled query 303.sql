select
  id,
  status,
  provider_league_id,
  provider_season_ids,
  matches_scanned,
  matches_hydrated,
  matches_upserted,
  events_upserted,
  error,
  metadata -> 'event_sync' as event_sync,
  created_at
from public.sync_runs
order by created_at desc
limit 5;