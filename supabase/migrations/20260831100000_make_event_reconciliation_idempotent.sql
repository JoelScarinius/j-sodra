begin;

-- Idempotent event reconciliation. Unchanged event and team-stat rows are not rewritten.
-- Historical migrations remain unchanged.

create or replace function public.replace_match_events(
  p_match_id bigint,
  p_run_id text,
  p_attempt_id uuid,
  p_source_payload_count integer,
  p_events jsonb,
  p_team_stats jsonb
)
returns table (
  match_id bigint,
  data_status public.events_data_status,
  source_payload_count integer,
  stored_count integer
)
language plpgsql
security definer
set search_path = public
as $$
#variable_conflict use_column
declare
  v_match           public.matches%rowtype;
  v_normalized      integer;
  v_stored          integer := 0;
  v_stats_written   integer := 0;
  v_events_inserted integer := 0;
  v_events_updated  integer := 0;
  v_events_deleted  integer := 0;
  v_events_unchanged integer := 0;
  v_missing_ids     integer;
  v_distinct_ids    integer;
  v_unmapped_teams  integer;
  v_teamless        integer;
  v_bad_teamless    integer;
  v_foreign_team    integer;
  v_collisions      integer;
  v_data_status     public.events_data_status;
  v_has_events      boolean;
  v_stat_teams      bigint[];
begin
  ---------------------------------------------------------------------------
  -- 0. Shape validation, before any destructive statement.
  ---------------------------------------------------------------------------
  if p_run_id is null or btrim(p_run_id) = '' then
    raise exception 'replace_match_events: p_run_id is required'
      using errcode = '22023';
  end if;

  if p_attempt_id is null then
    raise exception 'replace_match_events: p_attempt_id is required'
      using errcode = '22023';
  end if;

  if p_events is null or jsonb_typeof(p_events) <> 'array' then
    raise exception 'replace_match_events: p_events must be a json array'
      using errcode = '22023';
  end if;

  if p_team_stats is null or jsonb_typeof(p_team_stats) <> 'array'
     or jsonb_array_length(p_team_stats) <> 2 then
    raise exception 'replace_match_events: p_team_stats must contain exactly two rows'
      using errcode = '22023';
  end if;

  if p_source_payload_count is null or p_source_payload_count < 0 then
    raise exception 'replace_match_events: p_source_payload_count must be a non-negative integer'
      using errcode = '22023';
  end if;

  v_normalized := jsonb_array_length(p_events);

  -- Every source event must survive normalization. A short array means rows
  -- were dropped upstream; refuse rather than commit a partial replacement.
  if v_normalized <> p_source_payload_count then
    raise exception 'replace_match_events: source payload has % events but % were normalized for match %',
      p_source_payload_count, v_normalized, p_match_id
      using errcode = '23514';
  end if;

  -- Stable provider event ids are mandatory and must be unique in the payload.
  select count(*) filter (where nullif(btrim(coalesce(e->>'provider_event_id', '')), '') is null),
         count(distinct btrim(e->>'provider_event_id'))
    into v_missing_ids, v_distinct_ids
    from jsonb_array_elements(p_events) as e;

  if v_missing_ids > 0 then
    raise exception 'replace_match_events: % event(s) for match % are missing provider_event_id',
      v_missing_ids, p_match_id
      using errcode = '23502';
  end if;

  if v_distinct_ids <> v_normalized then
    raise exception 'replace_match_events: duplicate provider_event_id values in payload for match % (% rows, % distinct)',
      p_match_id, v_normalized, v_distinct_ids
      using errcode = '23505';
  end if;

  ---------------------------------------------------------------------------
  -- 1. Lock the match and verify the claim belongs to this run + attempt.
  ---------------------------------------------------------------------------
  select * into v_match from public.matches where id = p_match_id for update;

  if not found then
    raise exception 'replace_match_events: unknown match %', p_match_id
      using errcode = 'P0002';
  end if;

  if v_match.events_sync_run_id is distinct from p_run_id then
    raise exception 'replace_match_events: match % is claimed by run %, not %',
      p_match_id, v_match.events_sync_run_id, p_run_id
      using errcode = '55006';
  end if;

  if not exists (
    select 1 from public.event_sync_attempts a
     where a.attempt_id = p_attempt_id
       and a.match_id = p_match_id
       and a.run_id = p_run_id
       and a.finished_at is null
  ) then
    raise exception 'replace_match_events: attempt % is not an open attempt for match % in run %',
      p_attempt_id, p_match_id, p_run_id
      using errcode = '55006';
  end if;

  if v_match.home_team_id is null or v_match.away_team_id is null then
    raise exception 'replace_match_events: match % has no home/away team ids', p_match_id
      using errcode = '23502';
  end if;

  ---------------------------------------------------------------------------
  -- 2. Semantic validation of the event payload (still nothing deleted).
  ---------------------------------------------------------------------------
  -- 2a. Team identity. Two distinct failure categories, counted separately.
  select
    count(*) filter (
      where nullif(btrim(coalesce(e->>'provider_team_id', '')), '') is not null
        and nullif(btrim(coalesce(e->>'team_id', '')), '') is null
    ),
    count(*) filter (
      where nullif(btrim(coalesce(e->>'provider_team_id', '')), '') is null
        and nullif(btrim(coalesce(e->>'team_id', '')), '') is null
    ),
    count(*) filter (
      where nullif(btrim(coalesce(e->>'provider_team_id', '')), '') is null
        and nullif(btrim(coalesce(e->>'team_id', '')), '') is null
        and coalesce(nullif(e->>'event_type', ''), '') <> all (public.event_types_allowing_null_team())
    ),
    count(*) filter (
      where nullif(btrim(coalesce(e->>'team_id', '')), '') is not null
        and (e->>'team_id')::bigint not in (v_match.home_team_id, v_match.away_team_id)
    )
    into v_unmapped_teams, v_teamless, v_bad_teamless, v_foreign_team
    from jsonb_array_elements(p_events) as e;

  if v_unmapped_teams > 0 then
    raise exception 'replace_match_events: % event(s) for match % carry a provider team id that failed local mapping',
      v_unmapped_teams, p_match_id
      using errcode = '23503';
  end if;

  if v_bad_teamless > 0 then
    raise exception 'replace_match_events: % event(s) for match % have no team id but an event_type that requires one',
      v_bad_teamless, p_match_id
      using errcode = '23502';
  end if;

  if v_foreign_team > 0 then
    raise exception 'replace_match_events: % event(s) for match % reference a team that is not home (%) or away (%)',
      v_foreign_team, p_match_id, v_match.home_team_id, v_match.away_team_id
      using errcode = '23514';
  end if;

  -- 2b. A provider_event_id must never already belong to a different match.
  select count(*)
    into v_collisions
    from jsonb_array_elements(p_events) as e
    join public.events ex
      on ex.provider = coalesce(nullif(e->>'provider', ''), 'wyscout')
     and ex.provider_event_id = btrim(e->>'provider_event_id')
   where ex.match_id <> p_match_id;

  if v_collisions > 0 then
    raise exception 'replace_match_events: % provider_event_id value(s) in the payload for match % already belong to a different match',
      v_collisions, p_match_id
      using errcode = '23505';
  end if;

  -- 2c. Team-stat rows: exactly the two participants, correct orientation.
  select array_agg((s->>'team_id')::bigint order by (s->>'team_id')::bigint)
    into v_stat_teams
    from jsonb_array_elements(p_team_stats) as s;

  if v_stat_teams is null or array_length(v_stat_teams, 1) <> 2
     or v_stat_teams[1] = v_stat_teams[2]
     or v_stat_teams <> (
          select array_agg(t order by t)
            from unnest(array[v_match.home_team_id, v_match.away_team_id]) as t
        ) then
    raise exception 'replace_match_events: team stat rows for match % must be exactly {home=%, away=%}',
      p_match_id, v_match.home_team_id, v_match.away_team_id
      using errcode = '23514';
  end if;

  if exists (
    select 1
      from jsonb_array_elements(p_team_stats) as s
     where nullif(s->>'opponent_team_id', '')::bigint is distinct from
           case when (s->>'team_id')::bigint = v_match.home_team_id
                then v_match.away_team_id else v_match.home_team_id end
  ) then
    raise exception 'replace_match_events: team stat rows for match % have wrong opponent orientation', p_match_id
      using errcode = '23514';
  end if;

  if exists (
    select 1
      from jsonb_array_elements(p_team_stats) as s
     where coalesce(nullif(s->>'venue', ''), '') is distinct from
           case when (s->>'team_id')::bigint = v_match.home_team_id then 'home' else 'away' end
  ) then
    raise exception 'replace_match_events: team stat rows for match % have wrong venue orientation', p_match_id
      using errcode = '23514';
  end if;

  ---------------------------------------------------------------------------
  -- 3. Reconcile events idempotently. The complete payload has already passed
  -- validation. Unchanged rows are not updated, so their heap/index versions
  -- and updated_at values remain untouched.
  ---------------------------------------------------------------------------
  with incoming as materialized (
    select
      coalesce(nullif(e->>'provider', ''), 'wyscout') as provider,
      btrim(e->>'provider_event_id') as provider_event_id,
      p_match_id as match_id,
      v_match.season_id as season_id,
      v_match.league_id as league_id,
      nullif(e->>'team_id', '')::bigint as team_id,
      case
        when nullif(e->>'team_id', '')::bigint is null then null
        when (e->>'team_id')::bigint = v_match.home_team_id then v_match.away_team_id
        else v_match.home_team_id
      end as opponent_team_id,
      nullif(e->>'provider_player_id', '')::bigint as provider_player_id,
      nullif(e->>'event_type', '') as event_type,
      nullif(e->>'event_sub_type', '') as event_sub_type,
      nullif(e->>'period', '') as period,
      nullif(e->>'minute', '')::integer as minute,
      nullif(e->>'second', '')::integer as second,
      nullif(e->>'x', '')::double precision as x,
      nullif(e->>'y', '')::double precision as y,
      nullif(e->>'end_x', '')::double precision as end_x,
      nullif(e->>'end_y', '')::double precision as end_y,
      nullif(e->>'xg', '')::numeric as xg,
      nullif(e->>'xt', '')::numeric as xt,
      coalesce(nullif(e->>'is_shot', '')::boolean, false) as is_shot,
      coalesce(nullif(e->>'is_goal', '')::boolean, false) as is_goal,
      nullif(e->>'source_updated_at', '')::timestamptz as source_updated_at,
      coalesce(e->'payload', CAST('{}' AS jsonb)) as payload
    from jsonb_array_elements(p_events) as e
  ), upserted as (
    insert into public.events (
      provider, provider_event_id, match_id, season_id, league_id,
      team_id, opponent_team_id, provider_player_id,
      event_type, event_sub_type, period, minute, second,
      x, y, end_x, end_y, xg, xt, is_shot, is_goal,
      source_updated_at, payload
    )
    select
      provider, provider_event_id, match_id, season_id, league_id,
      team_id, opponent_team_id, provider_player_id,
      event_type, event_sub_type, period, minute, second,
      x, y, end_x, end_y, xg, xt, is_shot, is_goal,
      source_updated_at, payload
    from incoming
    on conflict (provider, provider_event_id) do update
    set
      match_id = excluded.match_id,
      season_id = excluded.season_id,
      league_id = excluded.league_id,
      team_id = excluded.team_id,
      opponent_team_id = excluded.opponent_team_id,
      provider_player_id = excluded.provider_player_id,
      event_type = excluded.event_type,
      event_sub_type = excluded.event_sub_type,
      period = excluded.period,
      minute = excluded.minute,
      second = excluded.second,
      x = excluded.x,
      y = excluded.y,
      end_x = excluded.end_x,
      end_y = excluded.end_y,
      xg = excluded.xg,
      xt = excluded.xt,
      is_shot = excluded.is_shot,
      is_goal = excluded.is_goal,
      source_updated_at = excluded.source_updated_at,
      payload = excluded.payload
    where (
      public.events.match_id,
      public.events.season_id,
      public.events.league_id,
      public.events.team_id,
      public.events.opponent_team_id,
      public.events.provider_player_id,
      public.events.event_type,
      public.events.event_sub_type,
      public.events.period,
      public.events.minute,
      public.events.second,
      public.events.x,
      public.events.y,
      public.events.end_x,
      public.events.end_y,
      public.events.xg,
      public.events.xt,
      public.events.is_shot,
      public.events.is_goal,
      public.events.payload
    ) is distinct from (
      excluded.match_id,
      excluded.season_id,
      excluded.league_id,
      excluded.team_id,
      excluded.opponent_team_id,
      excluded.provider_player_id,
      excluded.event_type,
      excluded.event_sub_type,
      excluded.period,
      excluded.minute,
      excluded.second,
      excluded.x,
      excluded.y,
      excluded.end_x,
      excluded.end_y,
      excluded.xg,
      excluded.xt,
      excluded.is_shot,
      excluded.is_goal,
      excluded.payload
    )
    returning (xmax = 0) as inserted
  )
  select
    count(*) filter (where inserted),
    count(*) filter (where not inserted)
  into v_events_inserted, v_events_updated
  from upserted;

  delete from public.events existing
  where existing.match_id = p_match_id
    and not exists (
      select 1
      from jsonb_array_elements(p_events) as source_event
      where existing.provider = coalesce(nullif(source_event->>'provider', ''), 'wyscout')
        and existing.provider_event_id = btrim(source_event->>'provider_event_id')
    );
  get diagnostics v_events_deleted = row_count;

  select count(*) into v_stored
  from public.events e
  where e.match_id = p_match_id;

  v_events_unchanged := greatest(
    0,
    p_source_payload_count - v_events_inserted - v_events_updated
  );

  if v_stored <> p_source_payload_count then
    raise exception 'replace_match_events: stored % rows for match % but source payload had %',
      v_stored, p_match_id, p_source_payload_count
      using errcode = '23514';
  end if;

  ---------------------------------------------------------------------------
  -- 4. Replace both team_match_stats rows in the same transaction.
  ---------------------------------------------------------------------------
  insert into public.team_match_stats (
    match_id, season_id, league_id, team_id, opponent_team_id,
    venue, match_status, match_kickoff_at, round_number, result,
    goals_for, goals_against, points,
    xg_for, xg_against, xp, xt_for, xt_against,
    shots, shots_on_target, corners, clean_sheet, event_count,
    has_event_data, has_shot_data, has_xg_data,
    has_xg_for_data, has_xg_against_data, has_xp_data,
    has_xt_data, has_corner_data,
    calculation_version, source_updated_at, payload
  )
  select
    p_match_id,
    v_match.season_id,
    v_match.league_id,
    (s->>'team_id')::bigint,
    case when (s->>'team_id')::bigint = v_match.home_team_id
         then v_match.away_team_id else v_match.home_team_id end,
    case when (s->>'team_id')::bigint = v_match.home_team_id then 'home' else 'away' end,
    coalesce(nullif(s->>'match_status', ''), v_match.status),
    v_match.kickoff_at,
    nullif(s->>'round_number', '')::integer,
    coalesce(nullif(s->>'result', ''), 'U'),
    coalesce(nullif(s->>'goals_for', '')::integer, 0),
    coalesce(nullif(s->>'goals_against', '')::integer, 0),
    coalesce(nullif(s->>'points', '')::integer, 0),
    nullif(s->>'xg_for', '')::numeric,
    nullif(s->>'xg_against', '')::numeric,
    nullif(s->>'xp', '')::numeric,
    nullif(s->>'xt_for', '')::numeric,
    nullif(s->>'xt_against', '')::numeric,
    nullif(s->>'shots', '')::integer,
    nullif(s->>'shots_on_target', '')::integer,
    nullif(s->>'corners', '')::integer,
    coalesce(nullif(s->>'clean_sheet', '')::boolean, false),
    nullif(s->>'event_count', '')::integer,
    coalesce(nullif(s->>'has_event_data', '')::boolean, false),
    coalesce(nullif(s->>'has_shot_data', '')::boolean, false),
    -- legacy combined flag = both directions covered
    (coalesce(nullif(s->>'has_xg_for_data', '')::boolean, false)
     and coalesce(nullif(s->>'has_xg_against_data', '')::boolean, false)),
    coalesce(nullif(s->>'has_xg_for_data', '')::boolean, false),
    coalesce(nullif(s->>'has_xg_against_data', '')::boolean, false),
    -- xP needs both directions, never one
    (coalesce(nullif(s->>'has_xg_for_data', '')::boolean, false)
     and coalesce(nullif(s->>'has_xg_against_data', '')::boolean, false)),
    coalesce(nullif(s->>'has_xt_data', '')::boolean, false),
    coalesce(nullif(s->>'has_corner_data', '')::boolean, false),
    nullif(s->>'calculation_version', ''),
    nullif(s->>'source_updated_at', '')::timestamptz,
    coalesce(s->'payload', '{}'::jsonb)
  from jsonb_array_elements(p_team_stats) as s
  on conflict (match_id, team_id) do update
  set
    season_id = excluded.season_id,
    league_id = excluded.league_id,
    opponent_team_id = excluded.opponent_team_id,
    venue = excluded.venue,
    match_status = excluded.match_status,
    match_kickoff_at = excluded.match_kickoff_at,
    round_number = excluded.round_number,
    result = excluded.result,
    goals_for = excluded.goals_for,
    goals_against = excluded.goals_against,
    points = excluded.points,
    xg_for = excluded.xg_for,
    xg_against = excluded.xg_against,
    xp = excluded.xp,
    xt_for = excluded.xt_for,
    xt_against = excluded.xt_against,
    shots = excluded.shots,
    shots_on_target = excluded.shots_on_target,
    corners = excluded.corners,
    clean_sheet = excluded.clean_sheet,
    event_count = excluded.event_count,
    has_event_data = excluded.has_event_data,
    has_shot_data = excluded.has_shot_data,
    has_xg_data = excluded.has_xg_data,
    has_xg_for_data = excluded.has_xg_for_data,
    has_xg_against_data = excluded.has_xg_against_data,
    has_xp_data = excluded.has_xp_data,
    has_xt_data = excluded.has_xt_data,
    has_corner_data = excluded.has_corner_data,
    calculation_version = excluded.calculation_version,
    source_updated_at = excluded.source_updated_at,
    payload = excluded.payload
  where (
    public.team_match_stats.season_id,
    public.team_match_stats.league_id,
    public.team_match_stats.opponent_team_id,
    public.team_match_stats.venue,
    public.team_match_stats.match_status,
    public.team_match_stats.match_kickoff_at,
    public.team_match_stats.round_number,
    public.team_match_stats.result,
    public.team_match_stats.goals_for,
    public.team_match_stats.goals_against,
    public.team_match_stats.points,
    public.team_match_stats.xg_for,
    public.team_match_stats.xg_against,
    public.team_match_stats.xp,
    public.team_match_stats.xt_for,
    public.team_match_stats.xt_against,
    public.team_match_stats.shots,
    public.team_match_stats.shots_on_target,
    public.team_match_stats.corners,
    public.team_match_stats.clean_sheet,
    public.team_match_stats.event_count,
    public.team_match_stats.has_event_data,
    public.team_match_stats.has_shot_data,
    public.team_match_stats.has_xg_data,
    public.team_match_stats.has_xg_for_data,
    public.team_match_stats.has_xg_against_data,
    public.team_match_stats.has_xp_data,
    public.team_match_stats.has_xt_data,
    public.team_match_stats.has_corner_data,
    public.team_match_stats.calculation_version,
    public.team_match_stats.payload
  ) is distinct from (
    excluded.season_id,
    excluded.league_id,
    excluded.opponent_team_id,
    excluded.venue,
    excluded.match_status,
    excluded.match_kickoff_at,
    excluded.round_number,
    excluded.result,
    excluded.goals_for,
    excluded.goals_against,
    excluded.points,
    excluded.xg_for,
    excluded.xg_against,
    excluded.xp,
    excluded.xt_for,
    excluded.xt_against,
    excluded.shots,
    excluded.shots_on_target,
    excluded.corners,
    excluded.clean_sheet,
    excluded.event_count,
    excluded.has_event_data,
    excluded.has_shot_data,
    excluded.has_xg_data,
    excluded.has_xg_for_data,
    excluded.has_xg_against_data,
    excluded.has_xp_data,
    excluded.has_xt_data,
    excluded.has_corner_data,
    excluded.calculation_version,
    excluded.payload
  );

  select count(*) into v_stats_written
  from public.team_match_stats s
  where s.match_id = p_match_id;

  if v_stats_written <> 2 then
    raise exception 'replace_match_events: expected 2 team_match_stats rows for match %, wrote %',
      p_match_id, v_stats_written
      using errcode = '23514';
  end if;

  ---------------------------------------------------------------------------
  -- 5. Update both status axes.
  ---------------------------------------------------------------------------
  v_has_events := p_source_payload_count > 0;
  v_data_status := case when v_has_events then 'reconciled'::public.events_data_status
                        else 'provider_empty'::public.events_data_status end;

  update public.matches
     set events_data_status          = v_data_status,
         events_stored_count         = v_stored,
         events_source_payload_count = p_source_payload_count,
         events_synced_at            = now(),
         events_last_attempt_status  = 'succeeded',
         events_last_attempt_at      = now(),
         events_sync_error           = null,
         events_empty_confirmations  = case
                                         when v_has_events then 0
                                         else events_empty_confirmations + 1
                                       end,
         events_claim_expires_at     = null,
         events_sync_run_id          = null,
         -- a reconciled match needs no retry; an empty payload gets rechecked
         events_next_retry_at        = case
                                         when v_has_events then null
                                         else now() + public.event_retry_backoff(events_empty_confirmations + 1)
                                       end
   where id = p_match_id;

  -- Close the open attempt row instead of inserting a second one.
  update public.event_sync_attempts
     set attempt_status               = 'succeeded',
         source_payload_count         = p_source_payload_count,
         normalized_count             = v_normalized,
         stored_count                 = v_stored,
         rejected_count               = 0,
         unmapped_provider_team_count = v_unmapped_teams,
         teamless_event_count         = v_teamless,
         error                        = null,
         finished_at                  = now()
   where attempt_id = p_attempt_id
     and match_id = p_match_id
     and run_id = p_run_id
     and finished_at is null;

  if not found then
    raise exception 'replace_match_events: failed to close attempt % for match % and run %',
      p_attempt_id, p_match_id, p_run_id using errcode = '55006';
  end if;

  return query select p_match_id, v_data_status, p_source_payload_count, v_stored;
end;
$$;


revoke all on function public.replace_match_events(bigint, text, uuid, integer, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.replace_match_events(bigint, text, uuid, integer, jsonb, jsonb) to service_role;

notify pgrst, 'reload schema';
commit;
