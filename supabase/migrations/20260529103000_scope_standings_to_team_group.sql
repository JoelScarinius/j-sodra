drop function if exists public.api_standings(bigint, text);

create or replace function public.api_standings(
  p_season_id bigint,
  p_snapshot_key text default 'current',
  p_team_id bigint default null
)
returns table (
  "position" integer,
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
  with recursive team_scope as (
    select p_team_id as team_id
    where p_team_id is not null

    union

    select
      case
        when m.home_team_id = team_scope.team_id then m.away_team_id
        else m.home_team_id
      end as team_id
    from public.matches m
    join team_scope
      on m.season_id = p_season_id
     and (m.home_team_id = team_scope.team_id or m.away_team_id = team_scope.team_id)
    where m.home_team_id is not null
      and m.away_team_id is not null
  )
  select
    s.position as "position",
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
    and (
      p_team_id is null
      or s.team_id in (
        select team_scope.team_id
        from team_scope
        where team_scope.team_id is not null
      )
    )
  order by s.position asc nulls last, t.name asc;
$$;

grant execute on function public.api_standings(bigint, text, bigint) to anon, authenticated;