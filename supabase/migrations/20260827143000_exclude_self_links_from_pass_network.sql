begin;

-- Exclude impossible self-recipient edges from the analytical passing network.
-- Source event rows remain unchanged in public.events for auditability.
create or replace function public.api_team_pass_network_by_match_ids_v2(
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
  player_rows jsonb;
  link_rows jsonb;
  valid_matches integer;
  included_passes integer;
  excluded_self_recipient_passes integer;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(
    p_season_id,
    p_team_id,
    p_match_ids
  );

  if sc.matches_in_scope > 20 then
    raise exception 'selected_pass_network_scope_too_large: maximum 20 matches'
      using errcode = '22023';
  end if;

  with eligible as (
    select e.*
    from public.events e
    where e.match_id = any(sc.match_ids)
      and e.season_id = p_season_id
      and e.team_id = p_team_id
      and lower(coalesce(e.event_type, '')) = 'pass'
      and e.pass_accurate is true
      and not (
        e.secondary_tags
        && array['corner', 'free_kick', 'throw_in', 'goal_kick', 'penalty']
      )
      and e.provider_player_id is not null
      and e.player_name is not null
      and e.recipient_provider_player_id is not null
      and e.recipient_provider_player_id <> e.provider_player_id
      and e.recipient_player_name is not null
  ),
  player_events as (
    select
      match_id,
      provider_player_id,
      player_name,
      player_position,
      x,
      y
    from eligible
    where x is not null
      and y is not null

    union all

    select
      match_id,
      recipient_provider_player_id,
      recipient_player_name,
      recipient_player_position,
      end_x,
      end_y
    from eligible
    where end_x is not null
      and end_y is not null
  ),
  per_match_player as (
    select
      match_id,
      provider_player_id,
      max(player_name) as player_name,
      max(player_position) as player_position,
      avg(x) as average_x,
      avg(y) as average_y,
      count(*) as involvements
    from player_events
    group by match_id, provider_player_id
  ),
  players as (
    select
      provider_player_id,
      max(player_name) as player_name,
      max(player_position) as player_position,
      avg(average_x) as average_x,
      avg(average_y) as average_y,
      sum(involvements) as involvements,
      count(*) as matches
    from per_match_player
    group by provider_player_id
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'provider_player_id', provider_player_id,
        'player_name', player_name,
        'player_position', player_position,
        'average_x', round(CAST(average_x AS numeric), 2),
        'average_y', round(CAST(average_y AS numeric), 2),
        'involvements', CAST(involvements AS integer),
        'matches', CAST(matches AS integer)
      )
      order by involvements desc, player_name, provider_player_id
    ),
    '[]'::jsonb
  ) into player_rows
  from players;

  with eligible as (
    select e.*
    from public.events e
    where e.match_id = any(sc.match_ids)
      and e.season_id = p_season_id
      and e.team_id = p_team_id
      and lower(coalesce(e.event_type, '')) = 'pass'
      and e.pass_accurate is true
      and not (
        e.secondary_tags
        && array['corner', 'free_kick', 'throw_in', 'goal_kick', 'penalty']
      )
      and e.provider_player_id is not null
      and e.player_name is not null
      and e.recipient_provider_player_id is not null
      and e.recipient_provider_player_id <> e.provider_player_id
      and e.recipient_player_name is not null
  ),
  links as (
    select
      provider_player_id as passer_provider_player_id,
      max(player_name) as passer_name,
      recipient_provider_player_id,
      max(recipient_player_name) as recipient_name,
      count(*) as completed_passes,
      count(distinct match_id) as matches
    from eligible
    group by provider_player_id, recipient_provider_player_id
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'passer_provider_player_id', passer_provider_player_id,
        'passer_name', passer_name,
        'recipient_provider_player_id', recipient_provider_player_id,
        'recipient_name', recipient_name,
        'completed_passes', CAST(completed_passes AS integer),
        'matches', CAST(matches AS integer)
      )
      order by
        completed_passes desc,
        passer_name,
        recipient_name,
        passer_provider_player_id,
        recipient_provider_player_id
    ),
    '[]'::jsonb
  ) into link_rows
  from links;

  select
    count(distinct e.match_id),
    count(*)
  into valid_matches, included_passes
  from public.events e
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and e.team_id = p_team_id
    and lower(coalesce(e.event_type, '')) = 'pass'
    and e.pass_accurate is true
    and not (
      e.secondary_tags
      && array['corner', 'free_kick', 'throw_in', 'goal_kick', 'penalty']
    )
    and e.provider_player_id is not null
    and e.player_name is not null
    and e.recipient_provider_player_id is not null
    and e.recipient_provider_player_id <> e.provider_player_id
    and e.recipient_player_name is not null;

  select count(*)
  into excluded_self_recipient_passes
  from public.events e
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and e.team_id = p_team_id
    and lower(coalesce(e.event_type, '')) = 'pass'
    and e.pass_accurate is true
    and not (
      e.secondary_tags
      && array['corner', 'free_kick', 'throw_in', 'goal_kick', 'penalty']
    )
    and e.provider_player_id is not null
    and e.player_name is not null
    and e.recipient_provider_player_id = e.provider_player_id
    and e.recipient_player_name is not null;

  return jsonb_build_object(
    'contract_version', 'analytics-api-v1',
    'methodology_version', 'passing-network-v1',
    'scope', jsonb_build_object(
      'season_id', p_season_id,
      'team_id', p_team_id,
      'scope_label', sc.scope_label,
      'scope_fingerprint', sc.scope_fingerprint,
      'query_fingerprint', sc.query_fingerprint,
      'match_ids', to_jsonb(sc.match_ids),
      'matches_in_scope', sc.matches_in_scope,
      'matches_with_event_coverage', sc.matches_with_event_coverage,
      'matches_with_network_data', coalesce(valid_matches, 0)
    ),
    'summary', jsonb_build_object(
      'accurate_open_play_recipient_backed_passes', coalesce(included_passes, 0),
      'excluded_self_recipient_passes', coalesce(excluded_self_recipient_passes, 0)
    ),
    'players', player_rows,
    'links', link_rows
  );
end;
$$;

revoke all on function public.api_team_pass_network_by_match_ids_v2(
  bigint,
  bigint,
  bigint[]
) from public, anon, authenticated;

grant execute on function public.api_team_pass_network_by_match_ids_v2(
  bigint,
  bigint,
  bigint[]
) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
commit;
