begin;

-- Persist normalized pass/player/possession fields derived from the retained
-- provider payload. Existing and future rows use one extraction function.
alter table public.events
  add column if not exists player_name text,
  add column if not exists player_position text,
  add column if not exists secondary_tags text[] not null default '{}',
  add column if not exists pass_accurate boolean,
  add column if not exists recipient_provider_player_id bigint,
  add column if not exists recipient_player_name text,
  add column if not exists recipient_player_position text,
  add column if not exists possession_id bigint,
  add column if not exists possession_duration double precision,
  add column if not exists possession_event_count integer,
  add column if not exists possession_event_index integer;

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

  select coalesce(array_agg(value order by ordinality), '{}'::text[])
    into new.secondary_tags
  from jsonb_array_elements_text(
    case
      when jsonb_typeof(new.payload #> '{type,secondary}') = 'array'
        then new.payload #> '{type,secondary}'
      else '[]'::jsonb
    end
  ) with ordinality as tags(value, ordinality);

  if lower(coalesce(new.event_type, '')) = 'pass' then
    new.pass_accurate := case
      when jsonb_typeof(new.payload #> '{pass,accurate}') = 'boolean'
        then (new.payload #>> '{pass,accurate}')::boolean
      else null
    end;
    v_recipient_id := case
      when coalesce(new.payload #>> '{pass,recipient,id}', '') ~ '^[0-9]+$'
        then (new.payload #>> '{pass,recipient,id}')::bigint
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
      then (new.payload #>> '{possession,id}')::bigint
    else null
  end;
  new.possession_duration := case
    when coalesce(new.payload #>> '{possession,duration}', '')
      ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'
      then (new.payload #>> '{possession,duration}')::double precision
    else null
  end;
  new.possession_event_count := case
    when coalesce(new.payload #>> '{possession,eventsNumber}', '') ~ '^[0-9]+$'
      then (new.payload #>> '{possession,eventsNumber}')::integer
    else null
  end;
  new.possession_event_index := case
    when coalesce(new.payload #>> '{possession,eventIndex}', '') ~ '^[0-9]+$'
      then (new.payload #>> '{possession,eventIndex}')::integer
    else null
  end;
  return new;
end;
$$;

drop trigger if exists populate_event_analysis_fields_on_events on public.events;
create trigger populate_event_analysis_fields_on_events
before insert or update of payload, event_type on public.events
for each row execute function public.populate_event_analysis_fields();

-- Backfill retained reconciled event rows without another provider fetch.
update public.events
set payload = payload;

create index if not exists idx_events_pass_team_scope
  on public.events (season_id, match_id, team_id, minute, second)
  where lower(coalesce(event_type, '')) = 'pass';

create index if not exists idx_events_pass_opponent_scope
  on public.events (season_id, match_id, opponent_team_id, minute, second)
  where lower(coalesce(event_type, '')) = 'pass';

-- Compact pass-vector contract for progression visualizations.
create or replace function public.api_team_passes_by_match_ids_v2(
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
  pass_rows jsonb;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(p_season_id, p_team_id, p_match_ids);

  if sc.matches_in_scope > 20 then
    raise exception 'selected_pass_scope_too_large: maximum 20 matches'
      using errcode = '22023';
  end if;

  select coalesce(jsonb_agg(
    jsonb_build_object(
      'match_id', e.match_id,
      'provider_match_id', m.provider_match_id,
      'kickoff_at', m.kickoff_at,
      'provider_event_id', e.provider_event_id,
      'team_id', e.team_id,
      'opponent_team_id', e.opponent_team_id,
      'provider_player_id', e.provider_player_id,
      'player_name', e.player_name,
      'player_position', e.player_position,
      'recipient_provider_player_id', e.recipient_provider_player_id,
      'recipient_player_name', e.recipient_player_name,
      'recipient_player_position', e.recipient_player_position,
      'event_sub_type', e.event_sub_type,
      'secondary_tags', to_jsonb(e.secondary_tags),
      'period', e.period,
      'minute', e.minute,
      'second', e.second,
      'x', e.x,
      'y', e.y,
      'end_x', e.end_x,
      'end_y', e.end_y,
      'pass_accurate', e.pass_accurate,
      'progression_gain', case when e.x is not null and e.end_x is not null then e.end_x - e.x else null end,
      'is_progressive_provider', 'progressive_pass' = any(e.secondary_tags),
      'is_progressive', coalesce(e.pass_accurate, false)
        and not (e.secondary_tags && array['corner','free_kick','throw_in','goal_kick','penalty'])
        and (
          'progressive_pass' = any(e.secondary_tags)
          or (e.x is not null and e.end_x is not null and e.end_x - e.x >= 15)
        ),
      'enters_final_third', e.x is not null and e.end_x is not null and e.x < 66.7 and e.end_x >= 66.7,
      'enters_penalty_area', e.end_x is not null and e.end_y is not null
        and e.end_x >= 83.0 and e.end_y between 21.0 and 79.0,
      'is_set_piece', e.secondary_tags && array['corner','free_kick','throw_in','goal_kick','penalty'],
      'team_perspective', case
        when e.team_id = p_team_id then 'for'
        when e.opponent_team_id = p_team_id then 'against'
        else 'match'
      end
    ) order by m.kickoff_at, e.match_id, e.minute, e.second, e.provider_event_id
  ), '[]'::jsonb) into pass_rows
  from public.events e
  join public.matches m on m.id = e.match_id
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and lower(coalesce(e.event_type, '')) = 'pass'
    and (e.team_id = p_team_id or e.opponent_team_id = p_team_id);

  return jsonb_build_object(
    'contract_version', 'analytics-api-v1',
    'methodology_version', 'pass-progression-v1',
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
    'passes', pass_rows
  );
end;
$$;

-- Server-aggregated directional passing network. Player positions are first
-- calculated per match, then averaged across matches so one high-volume match
-- does not define the multi-match position by itself.
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
  accurate_passes integer;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(p_season_id, p_team_id, p_match_ids);

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
      and not (e.secondary_tags && array['corner','free_kick','throw_in','goal_kick','penalty'])
      and e.provider_player_id is not null
      and e.player_name is not null
      and e.recipient_provider_player_id is not null
      and e.recipient_player_name is not null
  ), player_events as (
    select match_id, provider_player_id, player_name, player_position, x, y
    from eligible where x is not null and y is not null
    union all
    select match_id, recipient_provider_player_id, recipient_player_name,
           recipient_player_position, end_x, end_y
    from eligible where end_x is not null and end_y is not null
  ), per_match_player as (
    select match_id, provider_player_id,
           max(player_name) as player_name,
           max(player_position) as player_position,
           avg(x) as average_x,
           avg(y) as average_y,
           count(*)::integer as involvements
    from player_events
    group by match_id, provider_player_id
  ), players as (
    select provider_player_id,
           max(player_name) as player_name,
           max(player_position) as player_position,
           avg(average_x) as average_x,
           avg(average_y) as average_y,
           sum(involvements)::integer as involvements,
           count(*)::integer as matches
    from per_match_player
    group by provider_player_id
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'provider_player_id', provider_player_id,
    'player_name', player_name,
    'player_position', player_position,
    'average_x', round(average_x::numeric, 2),
    'average_y', round(average_y::numeric, 2),
    'involvements', involvements,
    'matches', matches
  ) order by involvements desc, player_name), '[]'::jsonb)
  into player_rows from players;

  with eligible as (
    select e.*
    from public.events e
    where e.match_id = any(sc.match_ids)
      and e.season_id = p_season_id
      and e.team_id = p_team_id
      and lower(coalesce(e.event_type, '')) = 'pass'
      and e.pass_accurate is true
      and not (e.secondary_tags && array['corner','free_kick','throw_in','goal_kick','penalty'])
      and e.provider_player_id is not null
      and e.player_name is not null
      and e.recipient_provider_player_id is not null
      and e.recipient_player_name is not null
  ), links as (
    select provider_player_id as passer_provider_player_id,
           max(player_name) as passer_name,
           recipient_provider_player_id,
           max(recipient_player_name) as recipient_name,
           count(*)::integer as completed_passes,
           count(distinct match_id)::integer as matches
    from eligible
    group by provider_player_id, recipient_provider_player_id
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'passer_provider_player_id', passer_provider_player_id,
    'passer_name', passer_name,
    'recipient_provider_player_id', recipient_provider_player_id,
    'recipient_name', recipient_name,
    'completed_passes', completed_passes,
    'matches', matches
  ) order by completed_passes desc, passer_name, recipient_name), '[]'::jsonb)
  into link_rows from links;

  select count(distinct e.match_id), count(*)
    into valid_matches, accurate_passes
  from public.events e
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and e.team_id = p_team_id
    and lower(coalesce(e.event_type, '')) = 'pass'
    and e.pass_accurate is true
    and not (e.secondary_tags && array['corner','free_kick','throw_in','goal_kick','penalty'])
    and e.provider_player_id is not null
    and e.recipient_provider_player_id is not null;

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
      'accurate_open_play_passes', coalesce(accurate_passes, 0)
    ),
    'players', player_rows,
    'links', link_rows
  );
end;
$$;

revoke all on function public.populate_event_analysis_fields() from public, anon, authenticated;
revoke all on function public.api_team_passes_by_match_ids_v2(bigint,bigint,bigint[]) from public, anon, authenticated;
revoke all on function public.api_team_pass_network_by_match_ids_v2(bigint,bigint,bigint[]) from public, anon, authenticated;
grant execute on function public.api_team_passes_by_match_ids_v2(bigint,bigint,bigint[]) to anon, authenticated, service_role;
grant execute on function public.api_team_pass_network_by_match_ids_v2(bigint,bigint,bigint[]) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
commit;
