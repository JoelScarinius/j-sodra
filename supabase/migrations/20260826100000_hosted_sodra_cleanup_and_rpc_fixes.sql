begin;

-- 1. Compatibility overload used by analytics v2 aggregate COUNT(*) values.
create or replace function public.metric_envelope(
  p_metric_name text,
  p_value numeric,
  p_matches_with_required_data bigint,
  p_matches_in_scope integer
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  select public.metric_envelope(
    p_metric_name,
    p_value,
    p_matches_with_required_data::integer,
    p_matches_in_scope
  );
$$;

-- 2. The event replacement RPC legitimately replaces thousands of rows in one
-- transaction. Supabase supports function-level statement_timeout for REST RPCs.
do $$
declare
  fn record;
begin
  for fn in
    select p.oid::regprocedure as signature
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'replace_match_events'
  loop
    execute format(
      'alter function %s set statement_timeout = %L',
      fn.signature,
      '60s'
    );
  end loop;
end;
$$;

-- 3. Remove only legacy Norra rows from hosted provider season 192451.
-- The connected component containing provider team 6849 is J-Sodra's division.
do $$
declare
  v_season_id bigint;
  v_anchor_team_id bigint;
  v_component_teams integer;
  v_season_teams integer;
  v_deleted_matches integer;
begin
  select s.id into v_season_id
  from public.seasons s
  where s.provider = 'wyscout'
    and s.provider_season_id = 192451;

  select t.id into v_anchor_team_id
  from public.teams t
  where t.provider = 'wyscout'
    and t.provider_team_id = 6849;

  if v_season_id is null or v_anchor_team_id is null then
    raise exception 'Sodra cleanup guard failed: season or J-Sodra team not found';
  end if;

  with recursive
  edges as (
    select m.home_team_id as a, m.away_team_id as b
    from public.matches m
    where m.season_id = v_season_id
      and m.home_team_id is not null
      and m.away_team_id is not null
    union all
    select m.away_team_id, m.home_team_id
    from public.matches m
    where m.season_id = v_season_id
      and m.home_team_id is not null
      and m.away_team_id is not null
  ),
  connected(team_id) as (
    select v_anchor_team_id
    union
    select e.b
    from edges e
    join connected c on c.team_id = e.a
  )
  select count(*) into v_component_teams from connected;

  select count(distinct participant.team_id)::integer into v_season_teams
  from public.matches m
  cross join lateral (
    values (m.home_team_id), (m.away_team_id)
  ) participant(team_id)
  where m.season_id = v_season_id
    and participant.team_id is not null;

  if v_component_teams <> 16 then
    raise exception 'Sodra cleanup guard failed: expected 16 connected teams, found %', v_component_teams;
  end if;

  if v_season_teams <= 16 then
    raise notice 'Season already scoped to % teams; no legacy matches deleted', v_season_teams;
  else
    with recursive
    edges as (
      select m.home_team_id as a, m.away_team_id as b
      from public.matches m
      where m.season_id = v_season_id
        and m.home_team_id is not null
        and m.away_team_id is not null
      union all
      select m.away_team_id, m.home_team_id
      from public.matches m
      where m.season_id = v_season_id
        and m.home_team_id is not null
        and m.away_team_id is not null
    ),
    connected(team_id) as (
      select v_anchor_team_id
      union
      select e.b from edges e join connected c on c.team_id = e.a
    )
    delete from public.matches m
    where m.season_id = v_season_id
      and (
        not exists (select 1 from connected c where c.team_id = m.home_team_id)
        or not exists (select 1 from connected c where c.team_id = m.away_team_id)
      );
    get diagnostics v_deleted_matches = row_count;

    with recursive
    edges as (
      select m.home_team_id as a, m.away_team_id as b
      from public.matches m
      where m.season_id = v_season_id
        and m.home_team_id is not null
        and m.away_team_id is not null
      union all
      select m.away_team_id, m.home_team_id
      from public.matches m
      where m.season_id = v_season_id
        and m.home_team_id is not null
        and m.away_team_id is not null
    ),
    connected(team_id) as (
      select v_anchor_team_id
      union
      select e.b from edges e join connected c on c.team_id = e.a
    )
    delete from public.season_teams st
    where st.season_id = v_season_id
      and not exists (select 1 from connected c where c.team_id = st.team_id);

    raise notice 'Deleted % legacy non-Sodra matches', v_deleted_matches;
  end if;

  perform public.refresh_season_derived_data(v_season_id, 'current');
end;
$$;

notify pgrst, 'reload schema';
commit;
