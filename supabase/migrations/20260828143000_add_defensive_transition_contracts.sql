begin;

create or replace function public.api_team_defensive_actions_by_match_ids_v2(
  p_season_id bigint,
  p_team_id bigint,
  p_match_ids bigint[]
)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
set statement_timeout = '30s'
as $$
declare
  sc record;
  action_rows jsonb;
  present_categories jsonb;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(p_season_id, p_team_id, p_match_ids);

  if sc.matches_in_scope > 20 then
    raise exception 'selected_defensive_scope_too_large: maximum 20 matches'
      using errcode = '22023';
  end if;

  with eligible as (
    select
      e.*,
      array(
        select tag
        from unnest(e.secondary_tags) as tag
        where tag in (
          'recovery',
          'counterpressing_recovery',
          'defensive_duel',
          'interception',
          'sliding_tackle'
        )
        order by tag
      ) as action_types
    from public.events e
    where e.season_id = p_season_id
      and e.match_id = any(sc.match_ids)
      and (e.team_id = p_team_id or e.opponent_team_id = p_team_id)
      and e.secondary_tags && array[
        'recovery',
        'counterpressing_recovery',
        'defensive_duel',
        'interception',
        'sliding_tackle'
      ]
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'match_id', e.match_id,
    'provider_match_id', m.provider_match_id,
    'kickoff_at', m.kickoff_at,
    'provider_event_id', e.provider_event_id,
    'team_id', e.team_id,
    'opponent_team_id', e.opponent_team_id,
    'team_perspective', case
      when e.team_id = p_team_id then 'for'
      when e.opponent_team_id = p_team_id then 'against'
      else 'match'
    end,
    'action_types', to_jsonb(e.action_types),
    'event_type', e.event_type,
    'event_sub_type', e.event_sub_type,
    'secondary_tags', to_jsonb(e.secondary_tags),
    'provider_player_id', nullif(e.provider_player_id, 0),
    'player_name', e.player_name,
    'player_position', e.player_position,
    'period', e.period,
    'minute', e.minute,
    'second', e.second,
    'x', e.x,
    'y', e.y
  ) order by m.kickoff_at, e.match_id, e.minute, e.second, e.provider_event_id), CAST('[]' AS jsonb))
  into action_rows
  from eligible e
  join public.matches m on m.id = e.match_id;

  with tags as (
    select distinct tag
    from public.events e
    cross join lateral unnest(e.secondary_tags) as tag
    where e.season_id = p_season_id
      and e.match_id = any(sc.match_ids)
      and (e.team_id = p_team_id or e.opponent_team_id = p_team_id)
      and tag in (
        'recovery',
        'counterpressing_recovery',
        'defensive_duel',
        'interception',
        'sliding_tackle'
      )
  )
  select coalesce(jsonb_agg(tag order by tag), CAST('[]' AS jsonb))
  into present_categories
  from tags;

  return jsonb_build_object(
    'contract_version', 'analytics-api-v1',
    'methodology_version', 'defensive-actions-v1',
    'scope', jsonb_build_object(
      'season_id', p_season_id,
      'team_id', p_team_id,
      'scope_label', sc.scope_label,
      'scope_fingerprint', sc.scope_fingerprint,
      'query_fingerprint', sc.query_fingerprint,
      'match_ids', to_jsonb(sc.match_ids),
      'matches_in_scope', sc.matches_in_scope,
      'matches_with_event_coverage', sc.matches_with_event_coverage
    ),
    'available_action_types', present_categories,
    'actions', action_rows
  );
end;
$$;

create or replace function public.api_team_transition_events_by_match_ids_v2(
  p_season_id bigint,
  p_team_id bigint,
  p_match_ids bigint[]
)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
set statement_timeout = '30s'
as $$
declare
  sc record;
  event_rows jsonb;
  present_categories jsonb;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(p_season_id, p_team_id, p_match_ids);

  if sc.matches_in_scope > 20 then
    raise exception 'selected_transition_scope_too_large: maximum 20 matches'
      using errcode = '22023';
  end if;

  with eligible as (
    select
      e.*,
      array(
        select tag
        from unnest(e.secondary_tags) as tag
        where tag in (
          'loose_ball_duel',
          'loss',
          'recovery',
          'counterpressing_recovery'
        )
        order by tag
      ) as transition_types
    from public.events e
    where e.season_id = p_season_id
      and e.match_id = any(sc.match_ids)
      and (e.team_id = p_team_id or e.opponent_team_id = p_team_id)
      and e.secondary_tags && array[
        'loose_ball_duel',
        'loss',
        'recovery',
        'counterpressing_recovery'
      ]
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'match_id', e.match_id,
    'provider_match_id', m.provider_match_id,
    'kickoff_at', m.kickoff_at,
    'provider_event_id', e.provider_event_id,
    'team_id', e.team_id,
    'opponent_team_id', e.opponent_team_id,
    'team_perspective', case
      when e.team_id = p_team_id then 'for'
      when e.opponent_team_id = p_team_id then 'against'
      else 'match'
    end,
    'transition_types', to_jsonb(e.transition_types),
    'event_type', e.event_type,
    'event_sub_type', e.event_sub_type,
    'secondary_tags', to_jsonb(e.secondary_tags),
    'provider_player_id', nullif(e.provider_player_id, 0),
    'player_name', e.player_name,
    'player_position', e.player_position,
    'possession_id', e.possession_id,
    'possession_event_index', e.possession_event_index,
    'possession_event_count', e.possession_event_count,
    'period', e.period,
    'minute', e.minute,
    'second', e.second,
    'x', e.x,
    'y', e.y
  ) order by m.kickoff_at, e.match_id, e.minute, e.second, e.provider_event_id), CAST('[]' AS jsonb))
  into event_rows
  from eligible e
  join public.matches m on m.id = e.match_id;

  with tags as (
    select distinct tag
    from public.events e
    cross join lateral unnest(e.secondary_tags) as tag
    where e.season_id = p_season_id
      and e.match_id = any(sc.match_ids)
      and (e.team_id = p_team_id or e.opponent_team_id = p_team_id)
      and tag in (
        'loose_ball_duel',
        'loss',
        'recovery',
        'counterpressing_recovery'
      )
  )
  select coalesce(jsonb_agg(tag order by tag), CAST('[]' AS jsonb))
  into present_categories
  from tags;

  return jsonb_build_object(
    'contract_version', 'analytics-api-v1',
    'methodology_version', 'transition-events-v1',
    'scope', jsonb_build_object(
      'season_id', p_season_id,
      'team_id', p_team_id,
      'scope_label', sc.scope_label,
      'scope_fingerprint', sc.scope_fingerprint,
      'query_fingerprint', sc.query_fingerprint,
      'match_ids', to_jsonb(sc.match_ids),
      'matches_in_scope', sc.matches_in_scope,
      'matches_with_event_coverage', sc.matches_with_event_coverage
    ),
    'available_transition_types', present_categories,
    'events', event_rows
  );
end;
$$;

revoke all on function public.api_team_defensive_actions_by_match_ids_v2(bigint, bigint, bigint[])
  from public, anon, authenticated;
revoke all on function public.api_team_transition_events_by_match_ids_v2(bigint, bigint, bigint[])
  from public, anon, authenticated;

grant execute on function public.api_team_defensive_actions_by_match_ids_v2(bigint, bigint, bigint[])
  to anon, authenticated, service_role;
grant execute on function public.api_team_transition_events_by_match_ids_v2(bigint, bigint, bigint[])
  to anon, authenticated, service_role;

notify pgrst, 'reload schema';
commit;
