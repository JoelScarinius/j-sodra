create or replace view public.v_team_season_options as
select
  l.id as league_id,
  l.provider_league_id,
  l.name as league_name,
  l.country_name as league_country_name,
  s.id as season_id,
  s.provider_season_id,
  s.name as season_name,
  s.start_date,
  s.end_date,
  s.is_current,
  t.id as team_id,
  t.provider_team_id,
  t.name as team_name,
  t.short_name as team_short_name,
  t.logo_url as team_logo_url,
  st.is_active
from public.season_teams st
join public.leagues l
  on l.id = st.league_id
join public.seasons s
  on s.id = st.season_id
join public.teams t
  on t.id = st.team_id;

create or replace view public.v_matches_flat as
select
  m.id,
  m.provider_match_id,
  m.league_id,
  l.provider_league_id,
  l.name as league_name,
  m.season_id,
  s.provider_season_id,
  s.name as season_name,
  m.round_number,
  m.stage_name,
  m.label,
  m.kickoff_at,
  m.status,
  m.venue_name,
  m.home_team_id,
  home_team.provider_team_id as home_provider_team_id,
  home_team.name as home_team_name,
  home_team.logo_url as home_team_logo_url,
  m.away_team_id,
  away_team.provider_team_id as away_provider_team_id,
  away_team.name as away_team_name,
  away_team.logo_url as away_team_logo_url,
  m.home_score,
  m.away_score,
  m.home_ht_score,
  m.away_ht_score
from public.matches m
join public.leagues l
  on l.id = m.league_id
join public.seasons s
  on s.id = m.season_id
left join public.teams home_team
  on home_team.id = m.home_team_id
left join public.teams away_team
  on away_team.id = m.away_team_id;

create or replace function public.api_filter_options(
  p_league_id bigint default null,
  p_season_id bigint default null
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with leagues_cte as (
  select
    id,
    provider_league_id,
    name,
    country_name,
    logo_url,
    is_active
  from public.leagues
  where p_league_id is null or id = p_league_id
  order by name
),
seasons_cte as (
  select
    id,
    league_id,
    provider_season_id,
    name,
    start_date,
    end_date,
    is_current
  from public.seasons
  where (p_league_id is null or league_id = p_league_id)
    and (p_season_id is null or id = p_season_id)
  order by start_date desc nulls last, provider_season_id desc
),
teams_cte as (
  select
    league_id,
    provider_league_id,
    league_name,
    season_id,
    provider_season_id,
    season_name,
    is_current,
    team_id,
    provider_team_id,
    team_name,
    team_short_name,
    team_logo_url
  from public.v_team_season_options
  where is_active
    and (p_league_id is null or league_id = p_league_id)
    and (p_season_id is null or season_id = p_season_id)
  order by team_name
)
select jsonb_build_object(
  'leagues', coalesce((select jsonb_agg(to_jsonb(leagues_cte) order by leagues_cte.name) from leagues_cte), '[]'::jsonb),
  'seasons', coalesce((select jsonb_agg(to_jsonb(seasons_cte) order by seasons_cte.start_date desc nulls last, seasons_cte.provider_season_id desc) from seasons_cte), '[]'::jsonb),
  'teams', coalesce((select jsonb_agg(to_jsonb(teams_cte) order by teams_cte.team_name) from teams_cte), '[]'::jsonb)
);
$$;

create or replace function public.api_standings(
  p_season_id bigint,
  p_snapshot_key text default 'current'
)
returns table (
  position integer,
  team_id bigint,
  provider_team_id bigint,
  team_name text,
  team_logo_url text,
  matches_played integer,
  wins integer,
  draws integer,
  losses integer,
  goals_for integer,
  goals_against integer,
  goal_difference integer,
  points integer,
  xg_for numeric,
  xg_against numeric,
  xp numeric,
  xt_for numeric,
  xt_against numeric
)
language sql
stable
security definer
set search_path = public
as $$
  select
    s.position,
    s.team_id,
    t.provider_team_id,
    t.name as team_name,
    t.logo_url as team_logo_url,
    s.matches_played,
    s.wins,
    s.draws,
    s.losses,
    s.goals_for,
    s.goals_against,
    s.goal_difference,
    s.points,
    s.xg_for,
    s.xg_against,
    s.xp,
    s.xt_for,
    s.xt_against
  from public.standings s
  join public.teams t
    on t.id = s.team_id
  where s.season_id = p_season_id
    and s.snapshot_key = p_snapshot_key
  order by s.position asc nulls last, t.name asc;
$$;

create or replace function public.api_team_matches(
  p_season_id bigint,
  p_team_id bigint,
  p_venue_filter text default 'all',
  p_limit integer default 10,
  p_offset integer default 0
)
returns table (
  match_id bigint,
  provider_match_id bigint,
  kickoff_at timestamptz,
  status text,
  round_number integer,
  venue text,
  result text,
  goals_for integer,
  goals_against integer,
  points integer,
  xg_for numeric,
  xg_against numeric,
  xp numeric,
  xt_for numeric,
  xt_against numeric,
  opponent_team_id bigint,
  opponent_provider_team_id bigint,
  opponent_team_name text,
  opponent_team_logo_url text,
  is_home boolean
)
language sql
stable
security definer
set search_path = public
as $$
  select
    tms.match_id,
    m.provider_match_id,
    tms.match_kickoff_at as kickoff_at,
    tms.match_status as status,
    tms.round_number,
    tms.venue,
    tms.result,
    tms.goals_for,
    tms.goals_against,
    tms.points,
    tms.xg_for,
    tms.xg_against,
    tms.xp,
    tms.xt_for,
    tms.xt_against,
    tms.opponent_team_id,
    opponent.provider_team_id as opponent_provider_team_id,
    opponent.name as opponent_team_name,
    opponent.logo_url as opponent_team_logo_url,
    (tms.venue = 'home') as is_home
  from public.team_match_stats tms
  join public.matches m
    on m.id = tms.match_id
  left join public.teams opponent
    on opponent.id = tms.opponent_team_id
  where tms.season_id = p_season_id
    and tms.team_id = p_team_id
    and (p_venue_filter = 'all' or tms.venue = p_venue_filter)
  order by tms.match_kickoff_at desc, tms.match_id desc
  limit greatest(p_limit, 1)
  offset greatest(p_offset, 0);
$$;

create or replace function public.api_team_metrics(
  p_season_id bigint,
  p_team_id bigint,
  p_venue_filter text default 'all',
  p_match_limit integer default null
)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  canonical_scope text;
  canonical_payload jsonb;
  dynamic_payload jsonb;
begin
  canonical_scope := case
    when p_match_limit = 5 and p_venue_filter = 'all' then 'last_5'
    when p_match_limit is null and p_venue_filter = 'home' then 'venue_home'
    when p_match_limit is null and p_venue_filter = 'away' then 'venue_away'
    when p_match_limit is null and p_venue_filter = 'all' then 'season_full'
    else null
  end;

  if canonical_scope is not null then
    select to_jsonb(ats)
    into canonical_payload
    from public.aggregated_team_stats ats
    where ats.season_id = p_season_id
      and ats.team_id = p_team_id
      and ats.snapshot_key = 'current'
      and ats.scope_key = canonical_scope
    order by ats.updated_at desc, ats.id desc
    limit 1;

    if canonical_payload is not null then
      return canonical_payload;
    end if;
  end if;

  with ranked as (
    select
      tms.*,
      row_number() over (
        partition by tms.team_id
        order by tms.match_kickoff_at desc, tms.match_id desc
      ) as recent_rank
    from public.team_match_stats tms
    where tms.season_id = p_season_id
      and tms.team_id = p_team_id
      and lower(tms.match_status) in ('played', 'complete', 'completed', 'finished', 'match ended')
      and (p_venue_filter = 'all' or tms.venue = p_venue_filter)
  ),
  scoped as (
    select *
    from ranked
    where p_match_limit is null or recent_rank <= greatest(p_match_limit, 1)
  )
  select jsonb_build_object(
    'season_id', p_season_id,
    'team_id', p_team_id,
    'venue_filter', p_venue_filter,
    'match_limit', p_match_limit,
    'matches_in_scope', count(scoped.id),
    'wins', coalesce(sum(case when scoped.result = 'W' then 1 else 0 end), 0),
    'draws', coalesce(sum(case when scoped.result = 'D' then 1 else 0 end), 0),
    'losses', coalesce(sum(case when scoped.result = 'L' then 1 else 0 end), 0),
    'points', coalesce(sum(scoped.points), 0),
    'points_per_match', case when count(scoped.id) > 0 then round(sum(scoped.points)::numeric / count(scoped.id), 4) else 0 end,
    'avg_goals_for', coalesce(avg(scoped.goals_for), 0),
    'avg_goals_against', coalesce(avg(scoped.goals_against), 0),
    'avg_xg_for', coalesce(avg(scoped.xg_for), 0),
    'avg_xg_against', coalesce(avg(scoped.xg_against), 0),
    'avg_xp', coalesce(avg(scoped.xp), 0),
    'avg_xt_for', coalesce(avg(scoped.xt_for), 0),
    'avg_xt_against', coalesce(avg(scoped.xt_against), 0),
    'form_sequence', coalesce(array_agg(scoped.result order by scoped.match_kickoff_at desc, scoped.match_id desc) filter (where scoped.result <> 'U'), '{}'::text[])
  )
  into dynamic_payload
  from scoped;

  return coalesce(dynamic_payload, '{}'::jsonb);
end;
$$;

create or replace function public.api_compare_team_seasons(
  p_team_id bigint,
  p_season_ids bigint[]
)
returns table (
  season_id bigint,
  provider_season_id bigint,
  season_name text,
  league_id bigint,
  league_name text,
  matches_in_scope integer,
  wins integer,
  draws integer,
  losses integer,
  points integer,
  points_per_match numeric,
  avg_goals_for numeric,
  avg_goals_against numeric,
  avg_xg_for numeric,
  avg_xg_against numeric,
  avg_xp numeric,
  avg_xt_for numeric,
  avg_xt_against numeric,
  current_position integer
)
language sql
stable
security definer
set search_path = public
as $$
  select
    ats.season_id,
    s.provider_season_id,
    s.name as season_name,
    ats.league_id,
    l.name as league_name,
    ats.matches_in_scope,
    ats.wins,
    ats.draws,
    ats.losses,
    ats.points,
    ats.points_per_match,
    ats.avg_goals_for,
    ats.avg_goals_against,
    ats.avg_xg_for,
    ats.avg_xg_against,
    ats.avg_xp,
    ats.avg_xt_for,
    ats.avg_xt_against,
    ats.current_position
  from public.aggregated_team_stats ats
  join public.seasons s
    on s.id = ats.season_id
  join public.leagues l
    on l.id = ats.league_id
  where ats.team_id = p_team_id
    and ats.scope_key = 'season_full'
    and ats.snapshot_key = 'current'
    and ats.season_id = any(p_season_ids)
  order by s.start_date desc nulls last, s.provider_season_id desc;
$$;

create or replace function public.api_dashboard_context(
  p_season_id bigint,
  p_team_id bigint
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with team_cte as (
  select
    t.id as team_id,
    t.provider_team_id,
    t.name,
    t.short_name,
    t.logo_url,
    s.id as season_id,
    s.provider_season_id,
    s.name as season_name,
    s.is_current,
    l.id as league_id,
    l.provider_league_id,
    l.name as league_name
  from public.teams t
  join public.season_teams st
    on st.team_id = t.id
   and st.season_id = p_season_id
  join public.seasons s
    on s.id = st.season_id
  join public.leagues l
    on l.id = st.league_id
  where t.id = p_team_id
  limit 1
),
upcoming_match as (
  select
    m.id,
    m.provider_match_id,
    m.kickoff_at,
    m.status,
    m.round_number,
    m.label,
    case when m.home_team_id = p_team_id then m.away_team_id else m.home_team_id end as opponent_team_id
  from public.matches m
  where m.season_id = p_season_id
    and (m.home_team_id = p_team_id or m.away_team_id = p_team_id)
    and lower(m.status) not in ('played', 'complete', 'completed', 'finished', 'match ended')
  order by m.kickoff_at asc nulls last, m.id asc
  limit 1
),
upcoming_enriched as (
  select
    upcoming_match.*,
    t.provider_team_id as opponent_provider_team_id,
    t.name as opponent_team_name,
    t.logo_url as opponent_team_logo_url
  from upcoming_match
  left join public.teams t
    on t.id = upcoming_match.opponent_team_id
),
latest_match as (
  select
    tms.match_id,
    m.provider_match_id,
    tms.match_kickoff_at as kickoff_at,
    tms.round_number,
    tms.venue,
    tms.result,
    tms.goals_for,
    tms.goals_against,
    tms.xg_for,
    tms.xg_against,
    tms.xp,
    tms.xt_for,
    tms.xt_against,
    tms.opponent_team_id,
    opponent.provider_team_id as opponent_provider_team_id,
    opponent.name as opponent_team_name,
    opponent.logo_url as opponent_team_logo_url
  from public.team_match_stats tms
  join public.matches m
    on m.id = tms.match_id
  left join public.teams opponent
    on opponent.id = tms.opponent_team_id
  where tms.season_id = p_season_id
    and tms.team_id = p_team_id
    and lower(tms.match_status) in ('played', 'complete', 'completed', 'finished', 'match ended')
  order by tms.match_kickoff_at desc, tms.match_id desc
  limit 1
),
standing_cte as (
  select *
  from public.standings
  where season_id = p_season_id
    and team_id = p_team_id
    and snapshot_key = 'current'
  limit 1
),
season_scope as (
  select *
  from public.aggregated_team_stats
  where season_id = p_season_id
    and team_id = p_team_id
    and snapshot_key = 'current'
    and scope_key = 'season_full'
  limit 1
),
last_five as (
  select *
  from public.aggregated_team_stats
  where season_id = p_season_id
    and team_id = p_team_id
    and snapshot_key = 'current'
    and scope_key = 'last_5'
  limit 1
)
select jsonb_build_object(
  'team', coalesce((select to_jsonb(team_cte) from team_cte), '{}'::jsonb),
  'next_match', coalesce((select to_jsonb(upcoming_enriched) from upcoming_enriched), 'null'::jsonb),
  'latest_match', coalesce((select to_jsonb(latest_match) from latest_match), 'null'::jsonb),
  'standing', coalesce((select to_jsonb(standing_cte) from standing_cte), '{}'::jsonb),
  'season_full', coalesce((select to_jsonb(season_scope) from season_scope), '{}'::jsonb),
  'last_five', coalesce((select to_jsonb(last_five) from last_five), '{}'::jsonb)
);
$$;

grant select on public.v_team_season_options to anon, authenticated;
grant select on public.v_matches_flat to anon, authenticated;

grant execute on function public.api_filter_options(bigint, bigint) to anon, authenticated;
grant execute on function public.api_standings(bigint, text) to anon, authenticated;
grant execute on function public.api_team_matches(bigint, bigint, text, integer, integer) to anon, authenticated;
grant execute on function public.api_team_metrics(bigint, bigint, text, integer) to anon, authenticated;
grant execute on function public.api_compare_team_seasons(bigint, bigint[]) to anon, authenticated;
grant execute on function public.api_dashboard_context(bigint, bigint) to anon, authenticated;

grant execute on function public.refresh_season_derived_data(bigint, text) to service_role;
grant execute on function public.recompute_standings_for_season(bigint, text) to service_role;
grant execute on function public.recompute_aggregated_team_stats(bigint, text) to service_role;