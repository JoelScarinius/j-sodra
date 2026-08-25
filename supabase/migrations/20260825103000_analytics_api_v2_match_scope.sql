begin;

drop function if exists public.api_resolve_match_scope_by_ids(bigint,bigint,bigint[]);
create function public.api_resolve_match_scope_by_ids(
  p_season_id bigint,
  p_team_id bigint,
  p_match_ids bigint[]
)
returns table(
  match_ids bigint[],
  matches_in_scope integer,
  matches_with_event_coverage integer,
  scope_label text,
  scope_fingerprint text,
  query_fingerprint text,
  season_name text,
  team_name text
)
language plpgsql stable security definer set search_path=public,extensions as $$
declare
  v_ids bigint[];
  v_covered integer;
  v_requested_count integer;
  v_selected_count integer;
  v_season_name text;
  v_team_name text;
begin
  perform public.assert_local_season(p_season_id);
  perform public.assert_local_team(p_team_id,p_season_id);

  if p_match_ids is null or cardinality(p_match_ids)=0 then
    raise exception 'match_ids_required' using errcode='22023';
  end if;

  select count(*)::integer into v_requested_count
  from (select distinct unnest(p_match_ids) as match_id) requested;

  with selected as (
    select m.id,m.kickoff_at
    from public.matches m
    where m.id=any(p_match_ids)
      and m.season_id=p_season_id
      and public.is_completed_match_status(m.status)
      and (m.home_team_id=p_team_id or m.away_team_id=p_team_id)
  )
  select coalesce(array_agg(id order by kickoff_at desc nulls last,id desc),'{}'::bigint[]),count(*)::integer
  into v_ids,v_selected_count
  from selected;

  if v_selected_count <> v_requested_count then
    raise exception 'invalid_match_scope: one or more match_ids are outside team/season/completed scope' using errcode='22023';
  end if;

  select count(*)::integer into v_covered
  from public.match_event_coverage
  where match_id=any(v_ids) and has_event_coverage;

  select name into v_season_name from public.seasons where id=p_season_id;
  select name into v_team_name from public.teams where id=p_team_id;

  return query
  select
    v_ids,
    cardinality(v_ids),
    coalesce(v_covered,0),
    format('selected matches (%s)',cardinality(v_ids)),
    'sha256:'||encode(digest('analytics-scope-v1|'||p_season_id||'|'||p_team_id||'|'||array_to_string(v_ids,','),'sha256'),'hex'),
    'sha256:'||encode(digest('analytics-query-v1|by-match-ids|'||p_season_id||'|'||p_team_id||'|'||array_to_string(v_ids,','),'sha256'),'hex'),
    v_season_name,
    v_team_name;
end $$;

drop function if exists public.api_team_metrics_by_match_ids_v2(bigint,bigint,bigint[]);
create function public.api_team_metrics_by_match_ids_v2(
  p_season_id bigint,
  p_team_id bigint,
  p_match_ids bigint[]
)
returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare
  sc record;
  r record;
  m jsonb;
  fixture_status text;
begin
  select * into sc from public.api_resolve_match_scope_by_ids(p_season_id,p_team_id,p_match_ids);

  select
    count(*) filter(where t.id is not null) fixture_matches,
    count(*) filter(where t.has_xg_for_data) xgf_n,
    count(*) filter(where t.has_xg_against_data) xga_n,
    count(*) filter(where t.has_xp_data) xp_n,
    count(*) filter(where t.has_xt_data) xt_n,
    count(*) filter(where t.has_shot_data) shot_n,
    count(*) filter(where t.has_corner_data) corner_n,
    sum(t.goals_for) gf,
    sum(t.goals_against) ga,
    sum(t.points) pts,
    sum(t.xg_for) filter(where t.has_xg_for_data) xgf,
    sum(t.xg_against) filter(where t.has_xg_against_data) xga,
    sum(t.xp) filter(where t.has_xp_data) xp,
    sum(t.xt_for) filter(where t.has_xt_data) xtf,
    sum(t.xt_against) filter(where t.has_xt_data) xta,
    sum(t.shots) filter(where t.has_shot_data) shots,
    sum(t.shots_on_target) filter(where t.has_shot_data) sot,
    sum(t.corners) filter(where t.has_corner_data) corners
  into r
  from unnest(sc.match_ids) ids(match_id)
  left join public.team_match_stats t on t.match_id=ids.match_id and t.team_id=p_team_id;

  fixture_status:=case
    when sc.matches_in_scope=0 then 'no_matches'
    when r.fixture_matches=0 then 'not_computed'
    when r.fixture_matches<sc.matches_in_scope then 'partial_coverage'
    else 'available'
  end;

  m:=jsonb_build_object(
    'matches_played',jsonb_build_object('value',sc.matches_in_scope,'status',case when sc.matches_in_scope=0 then 'no_matches' else 'available' end,'matches_with_required_data',sc.matches_in_scope,'matches_in_scope',sc.matches_in_scope),
    'points_per_match',jsonb_build_object('value',case when r.fixture_matches>0 then round(r.pts::numeric/r.fixture_matches,3) end,'status',fixture_status,'matches_with_required_data',r.fixture_matches,'matches_in_scope',sc.matches_in_scope),
    'goals_for',jsonb_build_object('value',case when r.fixture_matches>0 then r.gf end,'status',fixture_status,'matches_with_required_data',r.fixture_matches,'matches_in_scope',sc.matches_in_scope),
    'goals_against',jsonb_build_object('value',case when r.fixture_matches>0 then r.ga end,'status',fixture_status,'matches_with_required_data',r.fixture_matches,'matches_in_scope',sc.matches_in_scope)
  );

  m:=m
    ||public.metric_envelope('xg_for_total',r.xgf,r.xgf_n,sc.matches_in_scope)
    ||public.metric_envelope('xg_against_total',r.xga,r.xga_n,sc.matches_in_scope)
    ||public.metric_envelope('xg_for_per_match',case when r.xgf_n>0 then round(r.xgf/r.xgf_n,3) end,r.xgf_n,sc.matches_in_scope)
    ||public.metric_envelope('xg_against_per_match',case when r.xga_n>0 then round(r.xga/r.xga_n,3) end,r.xga_n,sc.matches_in_scope)
    ||public.metric_envelope('expected_points',r.xp,r.xp_n,sc.matches_in_scope)
    ||public.metric_envelope('xt_for_total',r.xtf,r.xt_n,sc.matches_in_scope)
    ||public.metric_envelope('xt_against_total',r.xta,r.xt_n,sc.matches_in_scope)
    ||public.metric_envelope('shots',r.shots,r.shot_n,sc.matches_in_scope)
    ||public.metric_envelope('shots_on_target',r.sot,r.shot_n,sc.matches_in_scope)
    ||public.metric_envelope('corners',r.corners,r.corner_n,sc.matches_in_scope);

  return jsonb_build_object(
    'contract_version','analytics-api-v1',
    'scope',jsonb_build_object(
      'season_id',p_season_id,
      'season_name',sc.season_name,
      'team_id',p_team_id,
      'team_name',sc.team_name,
      'scope_label',sc.scope_label,
      'scope_fingerprint',sc.scope_fingerprint,
      'query_fingerprint',sc.query_fingerprint,
      'match_ids',to_jsonb(sc.match_ids),
      'matches_in_scope',sc.matches_in_scope,
      'matches_with_event_coverage',sc.matches_with_event_coverage
    ),
    'metrics',m
  );
end $$;

drop function if exists public.api_team_matches_by_match_ids_v2(bigint,bigint,bigint[]);
create function public.api_team_matches_by_match_ids_v2(
  p_season_id bigint,
  p_team_id bigint,
  p_match_ids bigint[]
)
returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare
  sc record;
  rows jsonb;
begin
  select * into sc from public.api_resolve_match_scope_by_ids(p_season_id,p_team_id,p_match_ids);

  select coalesce(jsonb_agg(to_jsonb(x) order by x.kickoff_at desc),'[]'::jsonb) into rows
  from (
    select
      m.id match_id,
      m.provider_match_id,
      m.kickoff_at,
      m.status,
      m.round_number,
      case when m.home_team_id=p_team_id then 'home' else 'away' end venue,
      case when m.home_team_id=p_team_id then m.away_team_id else m.home_team_id end opponent_team_id,
      o.name opponent_team_name,
      o.logo_url opponent_team_logo_url,
      t.result,
      t.goals_for,
      t.goals_against,
      t.points,
      case when t.has_xg_for_data then t.xg_for end xg_for,
      case when t.has_xg_against_data then t.xg_against end xg_against,
      coalesce(t.has_xg_for_data,false) has_xg_for_data,
      coalesce(t.has_xg_against_data,false) has_xg_against_data,
      coalesce(t.has_shot_data,false) has_shot_data,
      c.events_data_status,
      c.ingestion_resolved,
      c.has_event_rows,
      c.has_event_coverage
    from unnest(sc.match_ids) ids(match_id)
    join public.matches m on m.id=ids.match_id
    left join public.team_match_stats t on t.match_id=m.id and t.team_id=p_team_id
    left join public.teams o on o.id=case when m.home_team_id=p_team_id then m.away_team_id else m.home_team_id end
    left join public.match_event_coverage c on c.match_id=m.id
  ) x;

  return jsonb_build_object(
    'contract_version','analytics-api-v1',
    'scope',jsonb_build_object(
      'scope_label',sc.scope_label,
      'scope_fingerprint',sc.scope_fingerprint,
      'query_fingerprint',sc.query_fingerprint,
      'match_ids',to_jsonb(sc.match_ids),
      'matches_in_scope',sc.matches_in_scope,
      'matches_with_event_coverage',sc.matches_with_event_coverage
    ),
    'matches',rows
  );
end $$;

revoke all on function public.api_resolve_match_scope_by_ids(bigint,bigint,bigint[]) from public,anon,authenticated;
revoke all on function public.api_team_metrics_by_match_ids_v2(bigint,bigint,bigint[]) from public,anon,authenticated;
revoke all on function public.api_team_matches_by_match_ids_v2(bigint,bigint,bigint[]) from public,anon,authenticated;

grant execute on function public.api_resolve_match_scope_by_ids(bigint,bigint,bigint[]) to service_role;
grant execute on function public.api_team_metrics_by_match_ids_v2(bigint,bigint,bigint[]) to anon,authenticated,service_role;
grant execute on function public.api_team_matches_by_match_ids_v2(bigint,bigint,bigint[]) to anon,authenticated,service_role;

commit;