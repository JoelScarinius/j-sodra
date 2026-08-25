#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
M="$ROOT/supabase/migrations"
F="$ROOT/supabase/functions/sync-league/index.ts"

required=(
  "$M/20260824100000_event_sync_state.sql"
  "$M/20260824101000_aggregate_nullability.sql"
  "$M/20260824102000_replace_match_events.sql"
  "$M/20260824103000_analytics_api_v2.sql"
  "$M/20260824104000_completeness_audit.sql"
  "$F"
)
for file in "${required[@]}"; do
  [[ -f "$file" ]] || { echo "MISSING: $file" >&2; exit 1; }
done

! grep -Eq 'recompute_aggregated_team_stats\(p_season_id bigint\)[[:space:]]*$' "$M/20260824101000_aggregate_nullability.sql"
! grep -Eq 'xg[[:space:]]*\+=[[:space:]]*Number\(event\?\.shot\?\.xg[[:space:]]*\?\?[[:space:]]*0\)' "$F"
grep -q 'event_fetch_requests' "$F"
grep -q 'provider_season_ids is required in full mode' "$F"
grep -q 'from public.matches m where m.season_id=p_season_id' "$M/20260824103000_analytics_api_v2.sql"
grep -q 'run_completeness_audit(p_season_ids bigint\[\])' "$M/20260824104000_completeness_audit.sql"
grep -q 'recompute_aggregated_team_stats(' "$M/20260824101000_aggregate_nullability.sql"
grep -q 'p_snapshot_key text default' "$M/20260824101000_aggregate_nullability.sql"

echo "static checks passed"
