begin;

-- Normalize nested pass data for every provider event that carries a pass
-- object, including corners, free kicks, throw-ins and goal kicks.
create or replace function public.populate_event_analysis_fields()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  v_recipient_id bigint;
begin
  new.player_name := nullif(btrim(new.payload #>> '{player,name}'), '');
  new.player_position := nullif(btrim(new.payload #>> '{player,position}'), '');

  select coalesce(array_agg(value order by ordinality), CAST('{}' AS text[]))
    into new.secondary_tags
  from jsonb_array_elements_text(
    case
      when jsonb_typeof(new.payload #> '{type,secondary}') = 'array'
        then new.payload #> '{type,secondary}'
      else CAST('[]' AS jsonb)
    end
  ) with ordinality as tags(value, ordinality);

  if jsonb_typeof(new.payload -> 'pass') = 'object' then
    new.pass_accurate := case
      when jsonb_typeof(new.payload #> '{pass,accurate}') = 'boolean'
        then CAST(new.payload #>> '{pass,accurate}' AS boolean)
      else null
    end;

    v_recipient_id := case
      when coalesce(new.payload #>> '{pass,recipient,id}', '') ~ '^[0-9]+$'
        then CAST(new.payload #>> '{pass,recipient,id}' AS bigint)
      else null
    end;

    new.recipient_provider_player_id := nullif(v_recipient_id, 0);
    new.recipient_player_name := nullif(btrim(new.payload #>> '{pass,recipient,name}'), '');
    new.recipient_player_position := nullif(btrim(new.payload #>> '{pass,recipient,position}'), '');
  else
    new.pass_accurate := null;
    new.recipient_provider_player_id := null;
    new.recipient_player_name := null;
    new.recipient_player_position := null;
  end if;

  new.possession_id := case
    when coalesce(new.payload #>> '{possession,id}', '') ~ '^[0-9]+$'
      then CAST(new.payload #>> '{possession,id}' AS bigint)
    else null
  end;

  new.possession_duration := case
    when coalesce(new.payload #>> '{possession,duration}', '')
      ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'
      then CAST(new.payload #>> '{possession,duration}' AS double precision)
    else null
  end;

  new.possession_event_count := case
    when coalesce(new.payload #>> '{possession,eventsNumber}', '') ~ '^[0-9]+$'
      then CAST(new.payload #>> '{possession,eventsNumber}' AS integer)
    else null
  end;

  new.possession_event_index := case
    when coalesce(new.payload #>> '{possession,eventIndex}', '') ~ '^[0-9]+$'
      then CAST(new.payload #>> '{possession,eventIndex}' AS integer)
    else null
  end;

  return new;
end;
$$;

-- Re-derive typed analysis fields from retained source payloads. No provider
-- request is made and no source payload is changed.
update public.events
set payload = payload
where jsonb_typeof(payload -> 'pass') = 'object'
   or lower(coalesce(event_type, '')) in (
     'corner',
     'free_kick',
     'throw_in',
     'goal_kick'
   );

create index if not exists idx_events_set_piece_team_scope
  on public.events (season_id, match_id, team_id, event_type, minute, second)
  where lower(coalesce(event_type, '')) in (
    'corner',
    'free_kick',
    'throw_in',
    'goal_kick'
  );

create index if not exists idx_events_set_piece_opponent_scope
  on public.events (season_id, match_id, opponent_team_id, event_type, minute, second)
  where lower(coalesce(event_type, '')) in (
    'corner',
    'free_kick',
    'throw_in',
    'goal_kick'
  );

create index if not exists idx_events_tagged_set_piece_shots_scope
  on public.events (season_id, match_id, team_id, minute, second)
  where is_shot is true
    and secondary_tags && array[
      'shot_after_corner',
      'shot_after_free_kick',
      'shot_after_throw_in'
    ];

create or replace function public.api_team_set_pieces_by_match_ids_v2(
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
  set_piece_rows jsonb;
  shot_rows jsonb;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(
    p_season_id,
    p_team_id,
    p_match_ids
  );

  if sc.matches_in_scope > 20 then
    raise exception 'selected_set_piece_scope_too_large: maximum 20 matches'
      using errcode = '22023';
  end if;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
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
        'set_piece_type', lower(e.event_type),
        'event_sub_type', e.event_sub_type,
        'secondary_tags', to_jsonb(e.secondary_tags),
        'provider_player_id', e.provider_player_id,
        'player_name', e.player_name,
        'player_position', e.player_position,
        'recipient_provider_player_id', e.recipient_provider_player_id,
        'recipient_player_name', e.recipient_player_name,
        'recipient_player_position', e.recipient_player_position,
        'pass_accurate', e.pass_accurate,
        'has_pass_object', jsonb_typeof(e.payload -> 'pass') = 'object',
        'period', e.period,
        'minute', e.minute,
        'second', e.second,
        'x', e.x,
        'y', e.y,
        'end_x', e.end_x,
        'end_y', e.end_y
      )
      order by
        m.kickoff_at,
        e.match_id,
        e.minute,
        e.second,
        e.provider_event_id
    ),
    CAST('[]' AS jsonb)
  ) into set_piece_rows
  from public.events e
  join public.matches m on m.id = e.match_id
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and lower(coalesce(e.event_type, '')) in (
      'corner',
      'free_kick',
      'throw_in',
      'goal_kick'
    )
    and (
      e.team_id = p_team_id
      or e.opponent_team_id = p_team_id
    );

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
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
        'follow_up_type', case
          when 'shot_after_corner' = any(e.secondary_tags)
            then 'shot_after_corner'
          when 'shot_after_free_kick' = any(e.secondary_tags)
            then 'shot_after_free_kick'
          when 'shot_after_throw_in' = any(e.secondary_tags)
            then 'shot_after_throw_in'
          else null
        end,
        'event_type', e.event_type,
        'event_sub_type', e.event_sub_type,
        'secondary_tags', to_jsonb(e.secondary_tags),
        'period', e.period,
        'minute', e.minute,
        'second', e.second,
        'x', e.x,
        'y', e.y,
        'xg', e.xg,
        'is_goal', e.is_goal
      )
      order by
        m.kickoff_at,
        e.match_id,
        e.minute,
        e.second,
        e.provider_event_id
    ),
    CAST('[]' AS jsonb)
  ) into shot_rows
  from public.events e
  join public.matches m on m.id = e.match_id
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and e.is_shot is true
    and e.secondary_tags && array[
      'shot_after_corner',
      'shot_after_free_kick',
      'shot_after_throw_in'
    ]
    and (
      e.team_id = p_team_id
      or e.opponent_team_id = p_team_id
    );

  return jsonb_build_object(
    'contract_version', 'analytics-api-v1',
    'methodology_version', 'set-pieces-v1',
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
    'set_pieces', set_piece_rows,
    'tagged_follow_up_shots', shot_rows
  );
end;
$$;

revoke all on function public.populate_event_analysis_fields()
  from public, anon, authenticated;

revoke all on function public.api_team_set_pieces_by_match_ids_v2(
  bigint,
  bigint,
  bigint[]
) from public, anon, authenticated;

grant execute on function public.api_team_set_pieces_by_match_ids_v2(
  bigint,
  bigint,
  bigint[]
) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
commit;
