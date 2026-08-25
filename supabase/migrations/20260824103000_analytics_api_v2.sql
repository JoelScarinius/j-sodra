-- Phase 3 - canonical local-id analytics API.
begin;
create extension if not exists pgcrypto with schema extensions;

create or replace function public.assert_local_season(p_season_id bigint) returns bigint language plpgsql stable set search_path=public as $$
begin
 if p_season_id is null then raise exception 'unknown_season' using errcode='22023'; end if;
 if not exists(select 1 from public.seasons where id=p_season_id) then
   if exists(select 1 from public.seasons where provider_season_id=p_season_id) then raise exception 'provider_id_supplied: % is provider_season_id',p_season_id using errcode='22023'; end if;
   raise exception 'unknown_season: %',p_season_id using errcode='P0002';
 end if; return p_season_id;
end $$;

create or replace function public.assert_local_team(p_team_id bigint,p_season_id bigint) returns bigint language plpgsql stable set search_path=public as $$
begin
 if p_team_id is null then raise exception 'unknown_team' using errcode='22023'; end if;
 if not exists(select 1 from public.teams where id=p_team_id) then
  if exists(select 1 from public.teams where provider_team_id=p_team_id) then raise exception 'provider_id_supplied: % is provider_team_id',p_team_id using errcode='22023'; end if;
  raise exception 'unknown_team: %',p_team_id using errcode='P0002';
 end if;
 if p_season_id is not null and not exists(select 1 from public.season_teams where season_id=p_season_id and team_id=p_team_id and is_active) then
  raise exception 'team_not_in_season: team % season %',p_team_id,p_season_id using errcode='P0002'; end if;
 return p_team_id;
end $$;

create or replace function public.metric_envelope(p_key text,p_value numeric,p_covered integer,p_in_scope integer) returns jsonb language plpgsql immutable set search_path=public as $$
begin
 if coalesce(p_covered,0)<0 or coalesce(p_covered,0)>coalesce(p_in_scope,0) then raise exception 'invalid_metric_coverage'; end if;
 if coalesce(p_covered,0)=0 and p_value is not null then raise exception 'numeric_value_without_coverage'; end if;
 return jsonb_build_object(p_key,jsonb_build_object(
  'value',case when coalesce(p_covered,0)>0 then p_value end,
  'status',case when coalesce(p_in_scope,0)=0 then 'no_matches' when coalesce(p_covered,0)=0 then 'not_computed' when p_covered<p_in_scope then 'partial_coverage' else 'available' end,
  'matches_with_required_data',coalesce(p_covered,0),'matches_in_scope',coalesce(p_in_scope,0)));
end $$;

drop function if exists public.api_resolve_match_scope(bigint,bigint,bigint,text,integer,timestamptz,timestamptz);
create function public.api_resolve_match_scope(p_season_id bigint,p_team_id bigint,p_opponent_team_id bigint default null,p_venue text default 'all',
 p_match_limit integer default null,p_date_from timestamptz default null,p_date_to timestamptz default null)
returns table(match_ids bigint[],matches_in_scope integer,matches_with_event_coverage integer,scope_label text,scope_fingerprint text,query_fingerprint text,
 season_name text,team_name text,venue text,match_limit integer,date_from timestamptz,date_to timestamptz)
language plpgsql stable security definer set search_path=public,extensions as $$
declare v_venue text:=lower(coalesce(p_venue,'all'));v_ids bigint[];v_covered int;v_season_name text;v_team_name text;v_label text;
begin
 perform public.assert_local_season(p_season_id); perform public.assert_local_team(p_team_id,p_season_id);
 if p_opponent_team_id=p_team_id then raise exception 'invalid_opponent' using errcode='22023'; end if;
 if p_opponent_team_id is not null then perform public.assert_local_team(p_opponent_team_id,p_season_id); end if;
 if v_venue not in('all','home','away') then raise exception 'invalid_venue' using errcode='22023'; end if;
 if p_match_limit is not null and p_match_limit<1 then raise exception 'invalid_match_limit' using errcode='22023'; end if;
 if p_date_from is not null and p_date_to is not null and p_date_from>p_date_to then raise exception 'invalid_date_range' using errcode='22023'; end if;
 select name into v_season_name from public.seasons where id=p_season_id; select name into v_team_name from public.teams where id=p_team_id;
 with candidates as (
  select m.id,m.kickoff_at,case when m.home_team_id=p_team_id then 'home' else 'away' end side,
         case when m.home_team_id=p_team_id then m.away_team_id else m.home_team_id end opponent
  from public.matches m where m.season_id=p_season_id and public.is_completed_match_status(m.status)
    and (m.home_team_id=p_team_id or m.away_team_id=p_team_id)
    and (p_date_from is null or m.kickoff_at>=p_date_from) and (p_date_to is null or m.kickoff_at<=p_date_to)
 ), selected as (select * from candidates where (v_venue='all' or side=v_venue) and (p_opponent_team_id is null or opponent=p_opponent_team_id)
  order by kickoff_at desc nulls last,id desc limit case when p_match_limit is null then null else p_match_limit end)
 select coalesce(array_agg(id order by kickoff_at,id),'{}'::bigint[]) into v_ids from selected;
 select count(*) into v_covered from public.match_event_coverage where match_id=any(v_ids) and has_event_coverage;
 v_label:=case when p_match_limit is null then v_season_name||' · full season' when p_match_limit=1 then 'latest match' else format('last %s matches',p_match_limit) end
   ||case when v_venue='all' then '' else ' · '||v_venue end
   ||case when p_opponent_team_id is null then '' else ' · vs '||(select name from public.teams where id=p_opponent_team_id) end;
 return query select v_ids,cardinality(v_ids),coalesce(v_covered,0),v_label,
  'sha256:'||encode(digest('analytics-scope-v1|'||p_season_id||'|'||p_team_id||'|'||array_to_string(v_ids,','),'sha256'),'hex'),
  'sha256:'||encode(digest('analytics-query-v1|'||p_season_id||'|'||p_team_id||'|'||coalesce(p_opponent_team_id::text,'-')||'|'||v_venue||'|'||coalesce(p_match_limit::text,'full')||'|'||coalesce(p_date_from::text,'-')||'|'||coalesce(p_date_to::text,'-'),'sha256'),'hex'),
  v_season_name,v_team_name,v_venue,p_match_limit,p_date_from,p_date_to;
end $$;

create or replace function public.api_team_metrics_v2(p_season_id bigint,p_team_id bigint,p_venue text default 'all',p_match_limit integer default null,
 p_opponent_team_id bigint default null,p_date_from timestamptz default null,p_date_to timestamptz default null) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare sc record;r record;m jsonb;fixture_status text;begin
 select * into sc from public.api_resolve_match_scope(p_season_id,p_team_id,p_opponent_team_id,p_venue,p_match_limit,p_date_from,p_date_to);
 select count(*) filter(where t.id is not null) fixture_matches,
  count(*) filter(where t.has_xg_for_data) xgf_n,count(*) filter(where t.has_xg_against_data) xga_n,count(*) filter(where t.has_xp_data) xp_n,
  count(*) filter(where t.has_xt_data) xt_n,count(*) filter(where t.has_shot_data) shot_n,count(*) filter(where t.has_corner_data) corner_n,
  sum(t.goals_for) gf,sum(t.goals_against) ga,sum(t.points) pts,
  sum(t.xg_for) filter(where t.has_xg_for_data) xgf,sum(t.xg_against) filter(where t.has_xg_against_data) xga,
  sum(t.xp) filter(where t.has_xp_data) xp,sum(t.xt_for) filter(where t.has_xt_data) xtf,sum(t.xt_against) filter(where t.has_xt_data) xta,
  sum(t.shots) filter(where t.has_shot_data) shots,sum(t.shots_on_target) filter(where t.has_shot_data) sot,sum(t.corners) filter(where t.has_corner_data) corners
 into r from unnest(sc.match_ids) ids(match_id) left join public.team_match_stats t on t.match_id=ids.match_id and t.team_id=p_team_id;
 fixture_status:=case when sc.matches_in_scope=0 then 'no_matches' when r.fixture_matches=0 then 'not_computed' when r.fixture_matches<sc.matches_in_scope then 'partial_coverage' else 'available' end;
 m:=jsonb_build_object(
  'matches_played',jsonb_build_object('value',sc.matches_in_scope,'status',case when sc.matches_in_scope=0 then 'no_matches' else 'available' end,'matches_with_required_data',sc.matches_in_scope,'matches_in_scope',sc.matches_in_scope),
  'points_per_match',jsonb_build_object('value',case when r.fixture_matches>0 then round(r.pts::numeric/r.fixture_matches,3) end,'status',fixture_status,'matches_with_required_data',r.fixture_matches,'matches_in_scope',sc.matches_in_scope),
  'goals_for',jsonb_build_object('value',case when r.fixture_matches>0 then r.gf end,'status',fixture_status,'matches_with_required_data',r.fixture_matches,'matches_in_scope',sc.matches_in_scope),
  'goals_against',jsonb_build_object('value',case when r.fixture_matches>0 then r.ga end,'status',fixture_status,'matches_with_required_data',r.fixture_matches,'matches_in_scope',sc.matches_in_scope));
 m:=m||public.metric_envelope('xg_for_total',r.xgf,r.xgf_n,sc.matches_in_scope)||public.metric_envelope('xg_against_total',r.xga,r.xga_n,sc.matches_in_scope)
  ||public.metric_envelope('xg_for_per_match',case when r.xgf_n>0 then round(r.xgf/r.xgf_n,3) end,r.xgf_n,sc.matches_in_scope)
  ||public.metric_envelope('xg_against_per_match',case when r.xga_n>0 then round(r.xga/r.xga_n,3) end,r.xga_n,sc.matches_in_scope)
  ||public.metric_envelope('expected_points',r.xp,r.xp_n,sc.matches_in_scope)||public.metric_envelope('xt_for_total',r.xtf,r.xt_n,sc.matches_in_scope)
  ||public.metric_envelope('xt_against_total',r.xta,r.xt_n,sc.matches_in_scope)||public.metric_envelope('shots',r.shots,r.shot_n,sc.matches_in_scope)
  ||public.metric_envelope('shots_on_target',r.sot,r.shot_n,sc.matches_in_scope)||public.metric_envelope('corners',r.corners,r.corner_n,sc.matches_in_scope);
 return jsonb_build_object('contract_version','analytics-api-v1','scope',jsonb_build_object('season_id',p_season_id,'season_name',sc.season_name,
  'team_id',p_team_id,'team_name',sc.team_name,'opponent_team_id',p_opponent_team_id,'venue',sc.venue,'match_limit',sc.match_limit,
  'date_from',sc.date_from,'date_to',sc.date_to,'scope_label',sc.scope_label,'scope_fingerprint',sc.scope_fingerprint,'query_fingerprint',sc.query_fingerprint,
  'match_ids',to_jsonb(sc.match_ids),'matches_in_scope',sc.matches_in_scope,'matches_with_event_coverage',sc.matches_with_event_coverage),'metrics',m);
end $$;

create or replace function public.api_team_matches_v2(p_season_id bigint,p_team_id bigint,p_venue text default 'all',p_match_limit integer default null,p_opponent_team_id bigint default null) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare sc record;rows jsonb;begin
 select * into sc from public.api_resolve_match_scope(p_season_id,p_team_id,p_opponent_team_id,p_venue,p_match_limit,null,null);
 select coalesce(jsonb_agg(to_jsonb(x) order by x.kickoff_at desc),'[]'::jsonb) into rows from (
  select m.id match_id,m.provider_match_id,m.kickoff_at,m.status,m.round_number,
   case when m.home_team_id=p_team_id then 'home' else 'away' end venue,
   case when m.home_team_id=p_team_id then m.away_team_id else m.home_team_id end opponent_team_id,o.name opponent_team_name,o.logo_url opponent_team_logo_url,
   t.result,t.goals_for,t.goals_against,t.points,case when t.has_xg_for_data then t.xg_for end xg_for,case when t.has_xg_against_data then t.xg_against end xg_against,
   coalesce(t.has_xg_for_data,false) has_xg_for_data,coalesce(t.has_xg_against_data,false) has_xg_against_data,coalesce(t.has_shot_data,false) has_shot_data,
   c.events_data_status,c.ingestion_resolved,c.has_event_rows,c.has_event_coverage
  from unnest(sc.match_ids) ids(match_id) join public.matches m on m.id=ids.match_id
  left join public.team_match_stats t on t.match_id=m.id and t.team_id=p_team_id
  left join public.teams o on o.id=case when m.home_team_id=p_team_id then m.away_team_id else m.home_team_id end
  left join public.match_event_coverage c on c.match_id=m.id) x;
 return jsonb_build_object('contract_version','analytics-api-v1','scope',jsonb_build_object('scope_label',sc.scope_label,'scope_fingerprint',sc.scope_fingerprint,
 'query_fingerprint',sc.query_fingerprint,'match_ids',to_jsonb(sc.match_ids),'matches_in_scope',sc.matches_in_scope,'matches_with_event_coverage',sc.matches_with_event_coverage),'matches',rows);
end $$;

revoke all on function public.assert_local_season(bigint) from public,anon,authenticated;
revoke all on function public.assert_local_team(bigint,bigint) from public,anon,authenticated;
revoke all on function public.metric_envelope(text,numeric,integer,integer) from public,anon,authenticated;
revoke all on function public.api_resolve_match_scope(bigint,bigint,bigint,text,integer,timestamptz,timestamptz) from public,anon,authenticated;
revoke all on function public.api_team_metrics_v2(bigint,bigint,text,integer,bigint,timestamptz,timestamptz) from public,anon,authenticated;
revoke all on function public.api_team_matches_v2(bigint,bigint,text,integer,bigint) from public,anon,authenticated;
grant execute on function public.api_resolve_match_scope(bigint,bigint,bigint,text,integer,timestamptz,timestamptz) to service_role;
grant execute on function public.api_team_metrics_v2(bigint,bigint,text,integer,bigint,timestamptz,timestamptz) to anon,authenticated,service_role;
grant execute on function public.api_team_matches_v2(bigint,bigint,text,integer,bigint) to anon,authenticated,service_role;
commit;
