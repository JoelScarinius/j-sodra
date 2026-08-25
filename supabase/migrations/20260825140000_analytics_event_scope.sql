begin;

-- Validated event rows for interactive selected-match visualizations.
-- Returns only normalized analytical fields, never the raw provider payload.
create or replace function public.api_team_events_by_match_ids_v2(
  p_season_id bigint,
  p_team_id bigint,
  p_match_ids bigint[]
)
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  sc record;
  rows jsonb;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(
    p_season_id,
    p_team_id,
    p_match_ids
  );

  if sc.matches_in_scope > 20 then
    raise exception 'selected_event_scope_too_large: maximum 20 matches'
      using errcode = '22023';
  end if;

  select coalesce(
    jsonb_agg(to_jsonb(x) order by x.kickoff_at, x.match_id, x.minute, x.second, x.provider_event_id),
    '[]'::jsonb
  ) into rows
  from (
    select
      e.match_id,
      m.provider_match_id,
      m.kickoff_at,
      e.provider_event_id,
      e.team_id,
      e.opponent_team_id,
      e.provider_player_id,
      e.event_type,
      e.event_sub_type,
      e.period,
      e.minute,
      e.second,
      e.x,
      e.y,
      e.end_x,
      e.end_y,
      e.xg,
      e.xt,
      e.is_shot,
      e.is_goal,
      case
        when e.team_id = p_team_id then 'for'
        when e.opponent_team_id = p_team_id then 'against'
        else 'match'
      end as team_perspective
    from public.events e
    join public.matches m on m.id = e.match_id
    where e.match_id = any(sc.match_ids)
      and e.season_id = p_season_id
      and (e.team_id = p_team_id or e.opponent_team_id = p_team_id or e.team_id is null)
  ) x;

  return jsonb_build_object(
    'contract_version', 'analytics-api-v1',
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
    'events', rows
  );
end;
$$;

revoke all on function public.api_team_events_by_match_ids_v2(bigint,bigint,bigint[])
from public, anon, authenticated;
grant execute on function public.api_team_events_by_match_ids_v2(bigint,bigint,bigint[])
to anon, authenticated, service_role;

commit;
