begin;

-- Audit indexes: event checks are season-scoped and shot reconciliation groups
-- by match/team. Existing match_id-only indexes cannot serve all these paths.
create index if not exists idx_events_season_match
  on public.events (season_id, match_id);
create index if not exists idx_events_season_match_team_shot
  on public.events (season_id, match_id, team_id)
  where is_shot;
create index if not exists idx_team_match_stats_season_match
  on public.team_match_stats (season_id, match_id);

create or replace function public.run_completeness_audit(p_season_ids bigint[])
returns table(
  check_name text,
  severity text,
  failure_count bigint,
  passed boolean
)
language plpgsql
stable
security definer
set search_path = public
set statement_timeout = '60s'
as $$
begin
  if p_season_ids is null or cardinality(p_season_ids)=0 then
    raise exception 'audit season scope is required' using errcode='22023';
  end if;
  return query
with
scoped_matches as materialized (
  select m.*
  from public.matches m
  where m.season_id = any(p_season_ids)
),
scoped_events as materialized (
  select e.*
  from public.events e
  join scoped_matches m on m.id = e.match_id
),
scoped_stats as materialized (
  select s.*
  from public.team_match_stats s
  join scoped_matches m on m.id = s.match_id
),
event_counts as materialized (
  select e.match_id, count(*)::bigint as actual_count
  from scoped_events e
  group by e.match_id
),
stat_counts as materialized (
  select s.match_id, count(*)::bigint as actual_count
  from scoped_stats s
  group by s.match_id
),
shot_aggregates as materialized (
  select
    e.match_id,
    e.team_id,
    count(*)::bigint as shots,
    count(*) filter (where e.xg is not null)::bigint as shots_with_xg,
    sum(e.xg)::numeric as xg
  from scoped_events e
  where e.is_shot
  group by e.match_id, e.team_id
),
coverage as materialized (
  select c.*
  from public.match_event_coverage c
  join scoped_matches m on m.id = c.match_id
),
checks(check_name,severity,failure_count) as (
  select 'completed_match_not_resolved','blocker',count(*)::bigint
  from scoped_matches m
  where public.is_completed_match_status(m.status)
    and m.events_data_status not in ('reconciled','provider_empty','unavailable')

  union all
  select 'reconciled_count_vs_source','blocker',count(*)::bigint
  from scoped_matches m
  where m.events_data_status='reconciled'
    and (m.events_stored_count is null
      or m.events_source_payload_count is null
      or m.events_stored_count<>m.events_source_payload_count)

  union all
  select 'reconciled_count_vs_table','blocker',count(*)::bigint
  from scoped_matches m
  left join event_counts ec on ec.match_id=m.id
  where m.events_data_status='reconciled'
    and coalesce(ec.actual_count,0) is distinct from m.events_stored_count

  union all
  select 'completed_match_stat_row_count','blocker',count(*)::bigint
  from scoped_matches m
  left join stat_counts sc on sc.match_id=m.id
  where public.is_completed_match_status(m.status)
    and coalesce(sc.actual_count,0)<>2

  union all
  select 'event_parent_dimension_mismatch','blocker',count(*)::bigint
  from scoped_events e
  join scoped_matches m on m.id=e.match_id
  where e.season_id is distinct from m.season_id
     or e.league_id is distinct from m.league_id

  union all
  select 'event_team_not_participant','blocker',count(*)::bigint
  from scoped_events e
  join scoped_matches m on m.id=e.match_id
  where e.team_id is not null
    and e.team_id not in (m.home_team_id,m.away_team_id)

  union all
  select 'teamless_event_requiring_team','blocker',count(*)::bigint
  from scoped_events e
  where e.team_id is null
    and coalesce(e.event_type,'')<>all(public.event_types_allowing_null_team())

  union all
  select 'stat_orientation_or_parent_mismatch','blocker',count(*)::bigint
  from scoped_stats s
  join scoped_matches m on m.id=s.match_id
  where s.team_id not in (m.home_team_id,m.away_team_id)
     or s.opponent_team_id is distinct from case when s.team_id=m.home_team_id then m.away_team_id else m.home_team_id end
     or s.venue is distinct from case when s.team_id=m.home_team_id then 'home' else 'away' end
     or s.season_id is distinct from m.season_id
     or s.league_id is distinct from m.league_id

  union all
  select 'invalid_provider_event_id','blocker',count(*)::bigint
  from scoped_events e
  where e.provider_event_id is null or btrim(e.provider_event_id)=''

  union all
  select 'duplicate_provider_event_id','blocker',count(*)::bigint
  from (
    select e.provider,e.provider_event_id
    from scoped_events e
    group by e.provider,e.provider_event_id
    having count(*)>1
  ) q

  union all
  select 'xg_for_reconciliation','blocker',count(*)::bigint
  from scoped_stats s
  left join shot_aggregates q
    on q.match_id=s.match_id and q.team_id=s.team_id
  where (s.has_xg_for_data and (
          coalesce(q.shots,0)<>coalesce(q.shots_with_xg,0)
          or s.xg_for is null
          or abs(s.xg_for-coalesce(q.xg,0))>0.01
        ))
     or (not s.has_xg_for_data and s.xg_for is not null)

  union all
  select 'xg_against_reconciliation','blocker',count(*)::bigint
  from scoped_stats s
  left join shot_aggregates q
    on q.match_id=s.match_id and q.team_id=s.opponent_team_id
  where (s.has_xg_against_data and (
          coalesce(q.shots,0)<>coalesce(q.shots_with_xg,0)
          or s.xg_against is null
          or abs(s.xg_against-coalesce(q.xg,0))>0.01
        ))
     or (not s.has_xg_against_data and s.xg_against is not null)

  union all
  select 'coverage_claimed_without_reconciled_events','blocker',count(*)::bigint
  from scoped_stats s
  join coverage c on c.match_id=s.match_id
  where (s.has_event_data or s.has_shot_data or s.has_corner_data)
    and not c.has_event_coverage

  union all
  select 'unavailable_match_claims_event_coverage','blocker',count(*)::bigint
  from scoped_matches m
  join coverage c on c.match_id=m.id
  where m.events_data_status='unavailable'
    and (c.has_event_rows or c.has_event_coverage)

  union all
  select 'zero_without_coverage','blocker',count(*)::bigint
  from scoped_stats s
  where (s.xg_for=0 and not s.has_xg_for_data)
     or (s.xg_against=0 and not s.has_xg_against_data)
     or (s.shots=0 and not s.has_shot_data)
     or (s.corners=0 and not s.has_corner_data)
     or (s.event_count=0 and not s.has_event_data)

  union all
  select 'stale_ingestion_lease','blocker',count(*)::bigint
  from scoped_matches m
  where m.events_last_attempt_status='in_progress'
    and m.events_claim_expires_at<now()

  union all
  select 'completed_match_never_attempted','blocker',count(*)::bigint
  from scoped_matches m
  where public.is_completed_match_status(m.status)
    and m.events_last_attempt_status='never_attempted'

  union all
  select 'current_unresolved_attempt_failure','blocker',count(*)::bigint
  from scoped_matches m
  where public.is_completed_match_status(m.status)
    and m.events_data_status='pending'
    and m.events_last_attempt_status in ('failed','count_mismatch')

  union all
  select 'historical_failed_attempts','info',count(*)::bigint
  from public.event_sync_attempts a
  join scoped_matches m on m.id=a.match_id
  where a.attempt_status in ('failed','count_mismatch')

  union all
  select 'provider_empty_matches','info',count(*)::bigint
  from scoped_matches m where m.events_data_status='provider_empty'

  union all
  select 'unavailable_matches','info',count(*)::bigint
  from scoped_matches m where m.events_data_status='unavailable'
)
select check_name,severity,failure_count,failure_count=0
from checks
order by (severity='blocker') desc,failure_count desc,check_name;
end;
$$;

revoke all on function public.run_completeness_audit(bigint[]) from public,anon,authenticated;
grant execute on function public.run_completeness_audit(bigint[]) to service_role;

notify pgrst, 'reload schema';
commit;
