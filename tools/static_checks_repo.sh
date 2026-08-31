#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
M="$ROOT/supabase/migrations"
F="$ROOT/supabase/functions/sync-league/index.ts"
I="$M/20260831100000_make_event_reconciliation_idempotent.sql"

required=(
  "$M/20260824100000_event_sync_state.sql"
  "$M/20260824101000_aggregate_nullability.sql"
  "$M/20260824102000_replace_match_events.sql"
  "$M/20260824103000_analytics_api_v2.sql"
  "$M/20260824104000_completeness_audit.sql"
  "$I"
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

grep -q 'create or replace function public.replace_match_events' "$I"
grep -q 'on conflict (provider, provider_event_id) do update' "$I"
grep -q 'is distinct from' "$I"
grep -q 'not exists (' "$I"
! grep -q 'delete from public.events e where e.match_id = p_match_id;' "$I"

grep -q 'source_updated_at: toIso(event?.updatedAt' "$F"
! grep -q 'source_updated_at: new Date().toISOString(),[[:space:]]*$' "$F"

if grep -R --include='*.sql' \
  --exclude='20260824102000_replace_match_events.sql' \
  --exclude='20260827130000_add_pass_analytics_contracts.sql' \
  --exclude='20260827160000_add_set_piece_analytics_contract.sql' \
  -Eq 'update[[:space:]]+public\.events[[:space:]]+set[[:space:]]+payload[[:space:]]*=[[:space:]]*payload' "$M"; then
  echo "New no-op public.events payload backfill detected." >&2
  exit 1
fi

echo "static checks passed"
