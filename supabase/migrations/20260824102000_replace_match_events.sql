-- Phase 2.3 — transactional event + aggregate replacement (schema-accurate rewrite).
-- Deployment order: apply AFTER 01 and 03.
--
-- Guarantees:
--   * the whole payload is validated BEFORE anything is deleted
--   * match_id / season_id / league_id are forced from the locked parent match row,
--     never read from payload JSON
--   * events and BOTH team_match_stats rows are replaced in one transaction
--   * any count mismatch raises, so PostgreSQL rolls back and the previously
--     complete data survives untouched
--   * a failed refresh never downgrades retained reconciled data, and always
--     schedules a retry through matches.events_next_retry_at
--   * missing, duplicate, or cross-match provider_event_id is rejected
--   * one audit row per attempt: claim inserts it, the terminal call closes it
--
-- Team identity contract for events:
--   * if the raw event carries a provider team id, local mapping is MANDATORY;
--     an unmapped provider team rejects the whole payload
--   * team_id may be null ONLY for event types listed in
--     public.event_types_allowing_null_team()
--   * both categories are counted separately in event_sync_attempts

begin;

-- Signatures changed in this revision (claim now returns the attempt_id,
-- replace/fail now take p_attempt_id), so the old versions must be dropped;
-- create or replace cannot change a return type or argument list.
drop function if exists public.claim_match_event_sync(bigint, text, integer);
drop function if exists public.replace_match_events(bigint, text, integer, jsonb, jsonb);
drop function if exists public.fail_match_event_sync(bigint, text, text, public.events_attempt_status, integer, integer, integer);
drop function if exists public.fail_match_event_sync(bigint, text, uuid, text, public.events_attempt_status, integer, integer, integer);
drop function if exists public.settle_provider_empty_matches(integer, integer);

-- ---------------------------------------------------------------------------
-- Event types that legitimately have no owning team in the normalized contract.
-- Anything else with a null team_id is a normalization bug and is rejected.
-- ---------------------------------------------------------------------------
create or replace function public.event_types_allowing_null_team()
returns text[]
language sql
immutable
set search_path = public
as $$
  select array[
    'game_interruption',
    'match_start',
    'match_end',
    'half_start',
    'half_end'
  ]::text[];
$$;

-- ---------------------------------------------------------------------------
-- Retry backoff for a given attempt count. Bounded so 'unavailable' is slow,
-- never terminal.
-- ---------------------------------------------------------------------------
create or replace function public.event_retry_backoff(p_attempts integer)
returns interval
language sql
immutable
set search_path = public
as $$
  select case
           when coalesce(p_attempts, 0) <= 1 then interval '15 minutes'
           when p_attempts = 2 then interval '1 hour'
           when p_attempts = 3 then interval '6 hours'
           when p_attempts = 4 then interval '1 day'
           else interval '7 days'
         end;
$$;

-- ---------------------------------------------------------------------------
-- Claim a match for hydration. Touches the attempt axis only.
-- Returns the attempt_id that the terminal call must close, or null when the
-- claim was refused (another live claim holds the match).
-- ---------------------------------------------------------------------------
create or replace function public.claim_match_event_sync(
  p_match_id bigint,
  p_run_id text,
  p_lease_seconds integer default 900
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_claimed boolean;
  v_attempt_id uuid;
begin
  if p_run_id is null or btrim(p_run_id) = '' then
    raise exception 'claim_match_event_sync: p_run_id is required'
      using errcode = '22023';
  end if;

  update public.matches m
     set events_last_attempt_status = 'in_progress',
         events_last_attempt_at     = now(),
         events_sync_run_id         = p_run_id,
         events_sync_attempts       = m.events_sync_attempts + 1,
         events_claim_expires_at    = now() + make_interval(secs => greatest(60, p_lease_seconds))
   where m.id = p_match_id
     and (
       m.events_last_attempt_status <> 'in_progress'
       or m.events_claim_expires_at is null
       or m.events_claim_expires_at < now()
     )
  returning true into v_claimed;

  if not coalesce(v_claimed, false) then
    return null;
  end if;

  insert into public.event_sync_attempts (match_id, run_id, attempt_status)
  values (p_match_id, p_run_id, 'in_progress')
  returning attempt_id into v_attempt_id;

  return v_attempt_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- Replace events + both team_match_stats rows for one match, atomically.
--
-- p_source_payload_count : number of event objects in the provider payload as
--                          parsed by the Edge Function (source_payload_count).
-- p_events               : normalized event objects, one per source event.
-- p_team_stats           : jsonb array of exactly two team_match_stats rows.
-- ---------------------------------------------------------------------------
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
  -- 3. Replace events. Identity columns are forced from the parent match.
  ---------------------------------------------------------------------------
  delete from public.events e where e.match_id = p_match_id;

  insert into public.events (
    provider, provider_event_id, match_id, season_id, league_id,
    team_id, opponent_team_id, provider_player_id,
    event_type, event_sub_type, period, minute, second,
    x, y, end_x, end_y, xg, xt, is_shot, is_goal,
    source_updated_at, payload
  )
  select
    coalesce(nullif(e->>'provider', ''), 'wyscout'),
    btrim(e->>'provider_event_id'),
    p_match_id,
    v_match.season_id,
    v_match.league_id,
    nullif(e->>'team_id', '')::bigint,
    case
      when nullif(e->>'team_id', '')::bigint is null then null
      when (e->>'team_id')::bigint = v_match.home_team_id then v_match.away_team_id
      else v_match.home_team_id
    end,
    nullif(e->>'provider_player_id', '')::bigint,
    nullif(e->>'event_type', ''),
    nullif(e->>'event_sub_type', ''),
    nullif(e->>'period', ''),
    nullif(e->>'minute', '')::integer,
    nullif(e->>'second', '')::integer,
    nullif(e->>'x', '')::double precision,
    nullif(e->>'y', '')::double precision,
    nullif(e->>'end_x', '')::double precision,
    nullif(e->>'end_y', '')::double precision,
    nullif(e->>'xg', '')::numeric,
    nullif(e->>'xt', '')::numeric,
    coalesce(nullif(e->>'is_shot', '')::boolean, false),
    coalesce(nullif(e->>'is_goal', '')::boolean, false),
    nullif(e->>'source_updated_at', '')::timestamptz,
    coalesce(e->'payload', '{}'::jsonb)
  from jsonb_array_elements(p_events) as e;

  get diagnostics v_stored = row_count;

  -- Post-insert reconciliation. Raising rolls the whole transaction back,
  -- which restores the previously complete event rows.
  if v_stored <> p_source_payload_count then
    raise exception 'replace_match_events: stored % rows for match % but source payload had %',
      v_stored, p_match_id, p_source_payload_count
      using errcode = '23514';
  end if;

  if (select count(*) from public.events e where e.match_id = p_match_id) <> p_source_payload_count then
    raise exception 'replace_match_events: post-write count check failed for match %', p_match_id
      using errcode = '23514';
  end if;

  ---------------------------------------------------------------------------
  -- 4. Replace both team_match_stats rows in the same transaction.
  ---------------------------------------------------------------------------
  delete from public.team_match_stats s where s.match_id = p_match_id;

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
  from jsonb_array_elements(p_team_stats) as s;

  get diagnostics v_stats_written = row_count;

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

-- ---------------------------------------------------------------------------
-- Record a failed attempt WITHOUT downgrading retained data.
-- Always schedules a retry: a failure over retained reconciled data keeps
-- serving that data and comes back later.
-- ---------------------------------------------------------------------------
create or replace function public.fail_match_event_sync(
  p_match_id bigint,
  p_run_id text,
  p_attempt_id uuid,
  p_error text,
  p_attempt_status public.events_attempt_status default 'failed',
  p_source_payload_count integer default null,
  p_normalized_count integer default null,
  p_rejected_count integer default null,
  p_unmapped_provider_team_count integer default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_attempts integer;
begin
  if p_run_id is null or btrim(p_run_id) = '' then
    raise exception 'fail_match_event_sync: p_run_id is required'
      using errcode = '22023';
  end if;

  select events_sync_attempts into v_attempts
    from public.matches where id = p_match_id;

  update public.matches m
     set events_last_attempt_status = p_attempt_status,
         events_last_attempt_at     = now(),
         events_sync_error          = left(coalesce(p_error, 'unknown error'), 2000),
         events_claim_expires_at    = null,
         events_sync_run_id          = null,
         -- retained data axis is untouched
         events_data_status         = m.events_data_status,
         -- but the match is always rescheduled; a failure is never terminal
         events_next_retry_at       = now() + public.event_retry_backoff(coalesce(v_attempts, 1))
   where m.id = p_match_id
     and m.events_sync_run_id is not distinct from p_run_id;

  if p_attempt_id is not null then
    update public.event_sync_attempts
       set attempt_status       = p_attempt_status,
           source_payload_count = p_source_payload_count,
           normalized_count     = p_normalized_count,
           rejected_count       = p_rejected_count,
           unmapped_provider_team_count = p_unmapped_provider_team_count,
           error                = left(coalesce(p_error, 'unknown error'), 2000),
           finished_at          = now()
     where attempt_id = p_attempt_id
       and match_id = p_match_id
       and run_id = p_run_id
       and finished_at is null;
    if not found then
      raise exception 'fail_match_event_sync: attempt % is not open for match % and run %',
        p_attempt_id, p_match_id, p_run_id using errcode = '55006';
    end if;
  else
    insert into public.event_sync_attempts (
      match_id, run_id, attempt_status, source_payload_count,
      normalized_count, rejected_count, unmapped_provider_team_count, error, finished_at
    )
    values (
      p_match_id, p_run_id, p_attempt_status, p_source_payload_count,
      p_normalized_count, p_rejected_count, p_unmapped_provider_team_count,
      left(coalesce(p_error, 'unknown error'), 2000), now()
    );
  end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- Retry policy for explicitly empty provider payloads.
-- 'unavailable' means "no event data after the configured retry policy".
-- It is NOT terminal: the match keeps a (long-interval) events_next_retry_at so
-- a later provider backfill or an administrative recheck can still reconcile it.
-- ---------------------------------------------------------------------------
create or replace function public.settle_provider_empty_matches(
  p_recent_hours integer default 168,
  p_max_confirmations integer default 3,
  p_recheck_interval interval default interval '7 days'
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated integer;
begin
  update public.matches m
     set events_data_status   = 'unavailable',
         events_next_retry_at = now() + p_recheck_interval
   where m.events_data_status = 'provider_empty'
     and m.events_empty_confirmations >= p_max_confirmations
     and m.kickoff_at < now() - make_interval(hours => p_recent_hours);

  get diagnostics v_updated = row_count;
  return v_updated;
end;
$$;

-- ---------------------------------------------------------------------------
-- Release claims whose lease expired (crashed run). Keeps the retry clock live.
-- ---------------------------------------------------------------------------
create or replace function public.release_stale_event_claims()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_released integer;
begin
  update public.matches m
     set events_last_attempt_status = 'failed',
         events_sync_error          = 'claim lease expired',
         events_claim_expires_at    = null,
         events_next_retry_at       = least(
           coalesce(m.events_next_retry_at, now()),
           now()
         )
   where m.events_last_attempt_status = 'in_progress'
     and m.events_claim_expires_at is not null
     and m.events_claim_expires_at < now();

  get diagnostics v_released = row_count;

  update public.event_sync_attempts a
     set attempt_status = 'failed',
         error          = coalesce(a.error, 'claim lease expired'),
         finished_at    = now()
   where a.finished_at is null
     and a.claimed_at < now() - interval '6 hours';

  return v_released;
end;
$$;

revoke all on function public.event_types_allowing_null_team() from public, anon, authenticated;
revoke all on function public.event_retry_backoff(integer) from public, anon, authenticated;
revoke all on function public.claim_match_event_sync(bigint, text, integer) from public, anon, authenticated;
revoke all on function public.replace_match_events(bigint, text, uuid, integer, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.fail_match_event_sync(bigint, text, uuid, text, public.events_attempt_status, integer, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.settle_provider_empty_matches(integer, integer, interval) from public, anon, authenticated;
revoke all on function public.release_stale_event_claims() from public, anon, authenticated;

grant execute on function public.event_types_allowing_null_team() to service_role;
grant execute on function public.event_retry_backoff(integer) to service_role;
grant execute on function public.claim_match_event_sync(bigint, text, integer) to service_role;
grant execute on function public.replace_match_events(bigint, text, uuid, integer, jsonb, jsonb) to service_role;
grant execute on function public.fail_match_event_sync(bigint, text, uuid, text, public.events_attempt_status, integer, integer, integer, integer) to service_role;
grant execute on function public.settle_provider_empty_matches(integer, integer, interval) to service_role;
grant execute on function public.release_stale_event_claims() to service_role;

commit;
