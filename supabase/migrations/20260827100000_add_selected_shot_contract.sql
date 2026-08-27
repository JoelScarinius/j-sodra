begin;

-- Compact, stable browser contract for shot-only interactive visualizations.
-- This avoids aggregating and transferring every event when the client only
-- needs shots. Local season, team, and match ids remain the analytical inputs.
create or replace function public.api_team_shots_by_match_ids_v2(
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
  shot_rows jsonb;
begin
  select * into sc
  from public.api_resolve_match_scope_by_ids(
    p_season_id,
    p_team_id,
    p_match_ids
  );

  if sc.matches_in_scope > 20 then
    raise exception 'selected_shot_scope_too_large: maximum 20 matches'
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
        'event_type', e.event_type,
        'event_sub_type', e.event_sub_type,
        'period', e.period,
        'minute', e.minute,
        'second', e.second,
        'x', e.x,
        'y', e.y,
        'xg', e.xg,
        'is_shot', e.is_shot,
        'is_goal', e.is_goal,
        'team_perspective', case
          when e.team_id = p_team_id then 'for'
          when e.opponent_team_id = p_team_id then 'against'
          else 'match'
        end
      )
      order by
        m.kickoff_at,
        e.match_id,
        e.minute,
        e.second,
        e.provider_event_id
    ),
    '[]'::jsonb
  ) into shot_rows
  from public.events e
  join public.matches m on m.id = e.match_id
  where e.match_id = any(sc.match_ids)
    and e.season_id = p_season_id
    and e.is_shot is true
    and (
      e.team_id = p_team_id
      or e.opponent_team_id = p_team_id
    );

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
    'shots', shot_rows
  );
end;
$$;

revoke all on function public.api_team_shots_by_match_ids_v2(bigint,bigint,bigint[])
from public, anon, authenticated;

grant execute on function public.api_team_shots_by_match_ids_v2(bigint,bigint,bigint[])
to anon, authenticated, service_role;

notify pgrst, 'reload schema';
commit;
