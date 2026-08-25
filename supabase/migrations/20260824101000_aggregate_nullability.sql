-- Phase 2.2 - honest nullable event metrics while preserving existing contracts.
begin;

alter table public.team_match_stats
  alter column shots drop not null, alter column shots drop default,
  alter column shots_on_target drop not null, alter column shots_on_target drop default,
  alter column corners drop not null, alter column corners drop default,
  alter column event_count drop not null, alter column event_count drop default;

alter table public.team_match_stats
  add column if not exists has_event_data boolean not null default false,
  add column if not exists has_shot_data boolean not null default false,
  add column if not exists has_xg_data boolean not null default false,
  add column if not exists has_xg_for_data boolean not null default false,
  add column if not exists has_xg_against_data boolean not null default false,
  add column if not exists has_xp_data boolean not null default false,
  add column if not exists has_xt_data boolean not null default false,
  add column if not exists has_corner_data boolean not null default false,
  add column if not exists calculation_version text;

-- Existing rows are deliberately untrusted until the controlled backfill reconciles them.
update public.team_match_stats
set xg_for=null, xg_against=null, xp=null, xt_for=null, xt_against=null,
    shots=null, shots_on_target=null, corners=null, event_count=null,
    has_event_data=false, has_shot_data=false, has_xg_data=false,
    has_xg_for_data=false, has_xg_against_data=false, has_xp_data=false,
    has_xt_data=false, has_corner_data=false, calculation_version=null
where match_id in (select id from public.matches where events_data_status <> 'reconciled');

alter table public.standings
  alter column xg_for drop not null, alter column xg_for drop default,
  alter column xg_against drop not null, alter column xg_against drop default,
  alter column xp drop not null, alter column xp drop default,
  alter column xt_for drop not null, alter column xt_for drop default,
  alter column xt_against drop not null, alter column xt_against drop default;

alter table public.aggregated_team_stats
  alter column avg_xg_for drop not null, alter column avg_xg_for drop default,
  alter column avg_xg_against drop not null, alter column avg_xg_against drop default,
  alter column avg_xp drop not null, alter column avg_xp drop default,
  alter column avg_xt_for drop not null, alter column avg_xt_for drop default,
  alter column avg_xt_against drop not null, alter column avg_xt_against drop default;

alter table public.aggregated_team_stats
  add column if not exists xg_for_covered_matches integer not null default 0,
  add column if not exists xg_against_covered_matches integer not null default 0,
  add column if not exists xp_covered_matches integer not null default 0,
  add column if not exists xt_covered_matches integer not null default 0,
  add column if not exists shot_covered_matches integer not null default 0,
  add column if not exists corner_covered_matches integer not null default 0;

create or replace function public.recompute_standings_for_season(
  p_season_id bigint, p_snapshot_key text default 'current'
) returns void language plpgsql security definer set search_path=public as $$
begin
  delete from public.standings where season_id=p_season_id and snapshot_key=p_snapshot_key;
  with registered as (
    select season_id, league_id, team_id from public.season_teams
    where season_id=p_season_id and is_active
  ), completed as (
    select * from public.team_match_stats
    where season_id=p_season_id and public.is_completed_match_status(match_status)
  ), latest as (
    select (array_agg(match_id order by match_kickoff_at desc, match_id desc))[1] as match_id,
           max(match_kickoff_at) as kickoff_at from completed
  ), rolled as (
    select r.season_id,r.league_id,r.team_id, count(c.id)::int matches_played,
      count(c.id) filter(where c.result='W')::int wins,
      count(c.id) filter(where c.result='D')::int draws,
      count(c.id) filter(where c.result='L')::int losses,
      coalesce(sum(c.goals_for),0)::int goals_for, coalesce(sum(c.goals_against),0)::int goals_against,
      coalesce(sum(c.goals_for-c.goals_against),0)::int goal_difference, coalesce(sum(c.points),0)::int points,
      case when count(c.id)>0 and count(c.id)=count(c.id) filter(where c.has_xg_for_data) then sum(c.xg_for) end::numeric(12,4) xg_for,
      case when count(c.id)>0 and count(c.id)=count(c.id) filter(where c.has_xg_against_data) then sum(c.xg_against) end::numeric(12,4) xg_against,
      case when count(c.id)>0 and count(c.id)=count(c.id) filter(where c.has_xp_data) then sum(c.xp) end::numeric(12,4) xp,
      case when count(c.id)>0 and count(c.id)=count(c.id) filter(where c.has_xt_data) then sum(c.xt_for) end::numeric(12,4) xt_for,
      case when count(c.id)>0 and count(c.id)=count(c.id) filter(where c.has_xt_data) then sum(c.xt_against) end::numeric(12,4) xt_against
    from registered r left join completed c on c.team_id=r.team_id and c.season_id=r.season_id
    group by r.season_id,r.league_id,r.team_id
  ), positioned as (
    select *, dense_rank() over(order by points desc,goal_difference desc,goals_for desc,team_id)::int position from rolled
  )
  insert into public.standings(season_id,league_id,team_id,snapshot_key,as_of_match_id,as_of_kickoff_at,
    matches_played,wins,draws,losses,goals_for,goals_against,goal_difference,points,xg_for,xg_against,xp,xt_for,xt_against,position,metadata)
  select p.season_id,p.league_id,p.team_id,p_snapshot_key,l.match_id,l.kickoff_at,p.matches_played,p.wins,p.draws,p.losses,
    p.goals_for,p.goals_against,p.goal_difference,p.points,p.xg_for,p.xg_against,p.xp,p.xt_for,p.xt_against,p.position,
    jsonb_build_object('season_id',p.season_id,'snapshot_key',p_snapshot_key)
  from positioned p cross join latest l;
end $$;

create or replace function public.recompute_aggregated_team_stats(
  p_season_id bigint, p_snapshot_key text default 'current'
) returns void language plpgsql security definer set search_path=public as $$
begin
  delete from public.aggregated_team_stats where season_id=p_season_id and snapshot_key=p_snapshot_key;
  with registered as (
    select season_id,league_id,team_id from public.season_teams where season_id=p_season_id and is_active
  ), completed as (
    select *, row_number() over(partition by team_id order by match_kickoff_at desc,match_id desc) recent_rank
    from public.team_match_stats where season_id=p_season_id and public.is_completed_match_status(match_status)
  ), templates(scope_key,scope_label,venue_filter,window_size) as (
    values ('season_full','Full season','all',null::int),('venue_home','Home only','home',null::int),
           ('venue_away','Away only','away',null::int),('last_5','Last 5 matches','all',5)
  ), scope_rows as (
    select r.season_id,r.league_id,r.team_id,t.scope_key,t.scope_label,t.venue_filter,t.window_size,
      c.id,c.match_id,c.match_kickoff_at,c.result,c.points,c.goals_for,c.goals_against,c.xg_for,c.xg_against,c.xp,
      c.xt_for,c.xt_against,c.clean_sheet,c.has_xg_for_data,c.has_xg_against_data,c.has_xp_data,c.has_xt_data,
      c.has_shot_data,c.has_corner_data
    from registered r cross join templates t left join completed c on c.team_id=r.team_id and c.season_id=r.season_id
      and (t.venue_filter='all' or c.venue=t.venue_filter) and (t.window_size is null or c.recent_rank<=t.window_size)
  ), rolled as (
    select season_id,league_id,team_id,scope_key,scope_label,venue_filter,window_size,
      count(id)::int matches_in_scope, count(id) filter(where result='W')::int wins,
      count(id) filter(where result='D')::int draws,count(id) filter(where result='L')::int losses,
      coalesce(sum(points),0)::int points,
      coalesce(array_agg(result order by match_kickoff_at desc,match_id desc) filter(where id is not null and result<>'U'),'{}'::text[]) form_sequence,
      coalesce(avg(goals_for),0)::numeric(12,4) avg_goals_for,coalesce(avg(goals_against),0)::numeric(12,4) avg_goals_against,
      avg(xg_for) filter(where has_xg_for_data)::numeric(12,4) avg_xg_for,
      avg(xg_against) filter(where has_xg_against_data)::numeric(12,4) avg_xg_against,
      avg(xp) filter(where has_xp_data)::numeric(12,4) avg_xp,
      avg(xt_for) filter(where has_xt_data)::numeric(12,4) avg_xt_for,
      avg(xt_against) filter(where has_xt_data)::numeric(12,4) avg_xt_against,
      coalesce(sum(case when clean_sheet then 1 else 0 end),0)::int clean_sheets,
      count(*) filter(where id is not null and has_xg_for_data)::int xg_for_covered_matches,
      count(*) filter(where id is not null and has_xg_against_data)::int xg_against_covered_matches,
      count(*) filter(where id is not null and has_xp_data)::int xp_covered_matches,
      count(*) filter(where id is not null and has_xt_data)::int xt_covered_matches,
      count(*) filter(where id is not null and has_shot_data)::int shot_covered_matches,
      count(*) filter(where id is not null and has_corner_data)::int corner_covered_matches,
      (array_agg(match_id order by match_kickoff_at desc,match_id desc) filter(where id is not null))[1] as as_of_match_id,
      max(match_kickoff_at) as as_of_kickoff_at
    from scope_rows group by season_id,league_id,team_id,scope_key,scope_label,venue_filter,window_size
  )
  insert into public.aggregated_team_stats(season_id,league_id,team_id,scope_key,snapshot_key,scope_label,venue_filter,window_size,
    as_of_match_id,as_of_kickoff_at,matches_in_scope,wins,draws,losses,points,points_per_match,form_sequence,avg_goals_for,
    avg_goals_against,avg_xg_for,avg_xg_against,avg_xp,avg_xt_for,avg_xt_against,clean_sheets,current_position,metadata,
    xg_for_covered_matches,xg_against_covered_matches,xp_covered_matches,xt_covered_matches,shot_covered_matches,corner_covered_matches)
  select r.season_id,r.league_id,r.team_id,r.scope_key,p_snapshot_key,r.scope_label,r.venue_filter,r.window_size,r.as_of_match_id,
    r.as_of_kickoff_at,r.matches_in_scope,r.wins,r.draws,r.losses,r.points,
    case when r.matches_in_scope>0 then round(r.points::numeric/r.matches_in_scope,4) else 0 end,r.form_sequence,r.avg_goals_for,
    r.avg_goals_against,r.avg_xg_for,r.avg_xg_against,r.avg_xp,r.avg_xt_for,r.avg_xt_against,r.clean_sheets,s.position,
    jsonb_build_object('season_id',r.season_id,'scope_key',r.scope_key,'snapshot_key',p_snapshot_key),
    r.xg_for_covered_matches,r.xg_against_covered_matches,r.xp_covered_matches,r.xt_covered_matches,r.shot_covered_matches,r.corner_covered_matches
  from rolled r left join public.standings s on s.season_id=r.season_id and s.team_id=r.team_id and s.snapshot_key=p_snapshot_key;
end $$;

create or replace function public.refresh_season_derived_data(
  p_season_id bigint,p_snapshot_key text default 'current'
) returns void language plpgsql security definer set search_path=public as $$
begin
  perform public.recompute_standings_for_season(p_season_id,p_snapshot_key);
  perform public.recompute_aggregated_team_stats(p_season_id,p_snapshot_key);
end $$;

revoke all on function public.recompute_standings_for_season(bigint,text) from public,anon,authenticated;
revoke all on function public.recompute_aggregated_team_stats(bigint,text) from public,anon,authenticated;
revoke all on function public.refresh_season_derived_data(bigint,text) from public,anon,authenticated;
grant execute on function public.recompute_standings_for_season(bigint,text) to service_role;
grant execute on function public.recompute_aggregated_team_stats(bigint,text) to service_role;
grant execute on function public.refresh_season_derived_data(bigint,text) to service_role;
commit;
