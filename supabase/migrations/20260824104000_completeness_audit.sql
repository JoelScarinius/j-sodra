-- Phase 4 - scoped completeness audit. This migration creates functions only.
begin;
drop function if exists public.run_completeness_audit();
create or replace function public.run_completeness_audit(p_season_ids bigint[])
returns table(check_name text,severity text,failure_count bigint,passed boolean) language plpgsql stable security definer set search_path=public as $$
begin
 if p_season_ids is null or cardinality(p_season_ids)=0 then raise exception 'audit season scope is required' using errcode='22023'; end if;
 return query with checks as (
  select 'completed_match_not_resolved'::text n,'blocker'::text sev,count(*)::bigint c from public.matches m where m.season_id=any(p_season_ids) and public.is_completed_match_status(m.status) and not (m.events_data_status in('reconciled','provider_empty','unavailable'))
  union all select 'reconciled_count_vs_source','blocker',count(*) from public.matches m where m.season_id=any(p_season_ids) and m.events_data_status='reconciled' and (m.events_stored_count is null or m.events_source_payload_count is null or m.events_stored_count<>m.events_source_payload_count)
  union all select 'reconciled_count_vs_table','blocker',count(*) from (select m.id from public.matches m left join public.events e on e.match_id=m.id where m.season_id=any(p_season_ids) and m.events_data_status='reconciled' group by m.id,m.events_stored_count having count(e.id) is distinct from m.events_stored_count)q
  union all select 'completed_match_stat_row_count','blocker',count(*) from (select m.id from public.matches m left join public.team_match_stats s on s.match_id=m.id where m.season_id=any(p_season_ids) and public.is_completed_match_status(m.status) group by m.id having count(s.id)<>2)q
  union all select 'event_parent_dimension_mismatch','blocker',count(*) from public.events e join public.matches m on m.id=e.match_id where m.season_id=any(p_season_ids) and (e.season_id is distinct from m.season_id or e.league_id is distinct from m.league_id)
  union all select 'event_team_not_participant','blocker',count(*) from public.events e join public.matches m on m.id=e.match_id where m.season_id=any(p_season_ids) and e.team_id is not null and e.team_id not in(m.home_team_id,m.away_team_id)
  union all select 'teamless_event_requiring_team','blocker',count(*) from public.events e where e.season_id=any(p_season_ids) and e.team_id is null and coalesce(e.event_type,'')<>all(public.event_types_allowing_null_team())
  union all select 'stat_orientation_or_parent_mismatch','blocker',count(*) from public.team_match_stats s join public.matches m on m.id=s.match_id where m.season_id=any(p_season_ids) and (s.team_id not in(m.home_team_id,m.away_team_id) or s.opponent_team_id is distinct from case when s.team_id=m.home_team_id then m.away_team_id else m.home_team_id end or s.venue is distinct from case when s.team_id=m.home_team_id then 'home' else 'away' end or s.season_id is distinct from m.season_id or s.league_id is distinct from m.league_id)
  union all select 'invalid_provider_event_id','blocker',count(*) from public.events e where e.season_id=any(p_season_ids) and (e.provider_event_id is null or btrim(e.provider_event_id)='')
  union all select 'duplicate_provider_event_id','blocker',count(*) from (select e.provider,e.provider_event_id from public.events e where e.season_id=any(p_season_ids) group by e.provider,e.provider_event_id having count(*)>1)q
  union all select 'xg_for_reconciliation','blocker',count(*) from public.team_match_stats s join public.matches m on m.id=s.match_id left join lateral(select count(*) shots,count(*) filter(where e.xg is not null) with_xg,sum(e.xg) xg from public.events e where e.match_id=s.match_id and e.team_id=s.team_id and e.is_shot)q on true where m.season_id=any(p_season_ids) and ((s.has_xg_for_data and (q.shots<>q.with_xg or s.xg_for is null or abs(s.xg_for-coalesce(q.xg,0))>0.01)) or (not s.has_xg_for_data and s.xg_for is not null))
  union all select 'xg_against_reconciliation','blocker',count(*) from public.team_match_stats s join public.matches m on m.id=s.match_id left join lateral(select count(*) shots,count(*) filter(where e.xg is not null) with_xg,sum(e.xg) xg from public.events e where e.match_id=s.match_id and e.team_id=s.opponent_team_id and e.is_shot)q on true where m.season_id=any(p_season_ids) and ((s.has_xg_against_data and (q.shots<>q.with_xg or s.xg_against is null or abs(s.xg_against-coalesce(q.xg,0))>0.01)) or (not s.has_xg_against_data and s.xg_against is not null))
  union all select 'coverage_claimed_without_reconciled_events','blocker',count(*) from public.team_match_stats s join public.matches m on m.id=s.match_id join public.match_event_coverage c on c.match_id=s.match_id where m.season_id=any(p_season_ids) and ((s.has_event_data or s.has_shot_data or s.has_corner_data) and not c.has_event_coverage)
  union all select 'unavailable_match_claims_event_coverage','blocker',count(*) from public.matches m join public.match_event_coverage c on c.match_id=m.id where m.season_id=any(p_season_ids) and m.events_data_status='unavailable' and (c.has_event_rows or c.has_event_coverage)
  union all select 'zero_without_coverage','blocker',count(*) from public.team_match_stats s join public.matches m on m.id=s.match_id where m.season_id=any(p_season_ids) and ((s.xg_for=0 and not s.has_xg_for_data) or(s.xg_against=0 and not s.has_xg_against_data)or(s.shots=0 and not s.has_shot_data)or(s.corners=0 and not s.has_corner_data)or(s.event_count=0 and not s.has_event_data))
  union all select 'stale_ingestion_lease','blocker',count(*) from public.matches m where m.season_id=any(p_season_ids) and m.events_last_attempt_status='in_progress' and m.events_claim_expires_at<now()
  union all select 'completed_match_never_attempted','blocker',count(*) from public.matches m where m.season_id=any(p_season_ids) and public.is_completed_match_status(m.status) and m.events_last_attempt_status='never_attempted'
  union all select 'current_unresolved_attempt_failure','blocker',count(*) from public.matches m where m.season_id=any(p_season_ids) and public.is_completed_match_status(m.status) and m.events_data_status='pending' and m.events_last_attempt_status in('failed','count_mismatch')
  union all select 'historical_failed_attempts','info',count(*) from public.event_sync_attempts a join public.matches m on m.id=a.match_id where m.season_id=any(p_season_ids) and a.attempt_status in('failed','count_mismatch')
  union all select 'provider_empty_matches','info',count(*) from public.matches m where m.season_id=any(p_season_ids) and m.events_data_status='provider_empty'
  union all select 'unavailable_matches','info',count(*) from public.matches m where m.season_id=any(p_season_ids) and m.events_data_status='unavailable'
 ) select n,sev,c,c=0 from checks order by (sev='blocker') desc,c desc,n;
end $$;

create or replace function public.assert_completeness(p_season_ids bigint[]) returns void language plpgsql security definer set search_path=public as $$
declare names text;begin
 select string_agg(check_name||'='||failure_count,', ' order by check_name) into names from public.run_completeness_audit(p_season_ids) where severity='blocker' and not passed;
 if names is not null then raise exception 'completeness audit failed: %',names using errcode='P0001'; end if;
end $$;
revoke all on function public.run_completeness_audit(bigint[]) from public,anon,authenticated;
revoke all on function public.assert_completeness(bigint[]) from public,anon,authenticated;
grant execute on function public.run_completeness_audit(bigint[]) to service_role;
grant execute on function public.assert_completeness(bigint[]) to service_role;
commit;
-- After resolving provider seasons to local ids:
-- select * from public.run_completeness_audit(array[<local_season_id>]::bigint[]);
-- select public.assert_completeness(array[<local_season_id>]::bigint[]);
