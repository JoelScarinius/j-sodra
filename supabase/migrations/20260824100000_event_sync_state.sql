-- Phase 2.1 — per-match event ingestion state (schema-accurate rewrite).
--
-- Verified against supabase/migrations/20260526120000_multiseason_core.sql:
--   event table            = public.events            (NOT match_events)
--   per-team match table   = public.team_match_stats  (NOT match_team_stats)
--
-- Two independent axes, because they answer different questions:
--   events_data_status         -> what is retained and trustworthy right now
--   events_last_attempt_status -> how the most recent refresh attempt went
-- A failed refresh must never downgrade previously reconciled retained data.
--
-- Three separate coverage questions are exposed (see match_event_coverage):
--   ingestion_resolved -> ingestion reached a definite answer for this match
--   has_event_rows     -> reconciled AND at least one row in public.events
--   has_event_coverage -> event-derived metrics/plots may be computed
-- 'provider_empty' is ingestion_resolved = true but has_event_coverage = false.
-- 'pending' is not resolved at all.
--
-- IMPORTANT: every pre-existing match starts at 'pending' BY DESIGN. Existing
-- rows in public.events are left physically intact, but 'reconciled' is never
-- inferred from row existence — only a controlled backfill that reconciles the
-- source payload count may set it.
--
-- Additive and idempotent.

begin;

-- ---------------------------------------------------------------------------
-- 0. THE shared completed-status helper, defined first so every later file
--    (02, 03, 04, 05), the Edge Function and the Python pipeline agree.
--    Exactly these five values mean "this match is played and countable".
--    Anything else non-empty is unknown and fails closed (not counted).
-- ---------------------------------------------------------------------------
create or replace function public.completed_match_statuses()
returns text[]
language sql
immutable
set search_path = public
as $$
  select array['played', 'complete', 'completed', 'finished', 'match ended']::text[];
$$;

create or replace function public.is_completed_match_status(p_status text)
returns boolean
language sql
immutable
set search_path = public
as $$
  select coalesce(lower(btrim(p_status)) = any (public.completed_match_statuses()), false);
$$;

comment on function public.is_completed_match_status(text) is
  'Single source of truth for "this match is played". Unknown statuses fail closed. Never use result <> ''P''.';


do $$
begin
  if not exists (
    select 1
      from pg_type t
      join pg_namespace n on n.oid = t.typnamespace
     where t.typname = 'events_data_status'
       and n.nspname = 'public'
  ) then
    create type public.events_data_status as enum (
      'pending',        -- nothing reconciled has ever been stored for this match
      'reconciled',     -- stored rows matched the source payload exactly
      'provider_empty', -- provider explicitly returned an empty event array
      'unavailable'     -- no event data after the retry policy; RECOVERABLE, not terminal
    );
  end if;

  if not exists (
    select 1
      from pg_type t
      join pg_namespace n on n.oid = t.typnamespace
     where t.typname = 'events_attempt_status'
       and n.nspname = 'public'
  ) then
    create type public.events_attempt_status as enum (
      'never_attempted',
      'in_progress',
      'succeeded',
      'failed',
      'count_mismatch'
    );
  end if;
end $$;

alter table public.matches
  -- retained-data axis
  add column if not exists events_data_status public.events_data_status
    not null default 'pending',
  add column if not exists events_stored_count integer,
  add column if not exists events_synced_at timestamptz,
  add column if not exists events_empty_confirmations integer not null default 0,
  -- latest-attempt axis
  add column if not exists events_last_attempt_status public.events_attempt_status
    not null default 'never_attempted',
  add column if not exists events_last_attempt_at timestamptz,
  add column if not exists events_source_payload_count integer,
  add column if not exists events_sync_attempts integer not null default 0,
  add column if not exists events_sync_error text,
  add column if not exists events_sync_run_id text,
  -- claim lease: guards against two overlapping scheduled runs hydrating the
  -- same match and clobbering each other's replacement.
  add column if not exists events_claim_expires_at timestamptz,
  -- single retry clock for every "come back to this match later" case:
  --   * provider_empty recheck
  --   * failed / count_mismatch attempt sitting on top of retained reconciled data
  --   * slow recheck of 'unavailable' (which is never terminal)
  add column if not exists events_next_retry_at timestamptz;

alter table public.matches
  drop constraint if exists matches_events_stored_count_nonnegative,
  add constraint matches_events_stored_count_nonnegative
    check (events_stored_count is null or events_stored_count >= 0),
  drop constraint if exists matches_events_source_count_nonnegative,
  add constraint matches_events_source_count_nonnegative
    check (events_source_payload_count is null or events_source_payload_count >= 0),
  drop constraint if exists matches_events_reconciled_counts_present,
  add constraint matches_events_reconciled_counts_present
    check (events_data_status <> 'reconciled' or
           (events_stored_count is not null and events_source_payload_count is not null));

comment on column public.matches.events_data_status is
  'Retained event data state. Only ''reconciled'' with stored rows counts as event coverage; ''provider_empty'' is resolved-but-empty. Never downgraded by a failed refresh.';
comment on column public.matches.events_last_attempt_status is
  'Outcome of the most recent ingestion attempt. Orthogonal to events_data_status.';
comment on column public.matches.events_source_payload_count is
  'Number of event objects in the source payload the Edge Function parsed for the last attempt.';
comment on column public.matches.events_stored_count is
  'Rows actually present in public.events after the last successful transactional replacement.';
comment on column public.matches.events_empty_confirmations is
  'How many consecutive attempts saw an explicitly empty provider payload. Drives the provider_empty retry policy.';
comment on column public.matches.events_next_retry_at is
  'Earliest time this match should be considered again for event hydration. Set for provider_empty rechecks, failed attempts over retained data, and slow rechecks of ''unavailable''. Null means no scheduled retry.';

create index if not exists matches_events_data_status_idx
  on public.matches (season_id, events_data_status);

create index if not exists matches_events_incomplete_idx
  on public.matches (season_id)
  where events_data_status <> 'reconciled';

create index if not exists matches_events_retry_due_idx
  on public.matches (events_next_retry_at)
  where events_next_retry_at is not null;

-- One row per attempt. claim_match_event_sync() INSERTs the row (attempt_id,
-- claimed_at, attempt_status = 'in_progress'); the terminal call UPDATEs the
-- same row with finished_at and the final status. No second row per attempt.
create table if not exists public.event_sync_attempts (
  id bigint generated by default as identity primary key,
  attempt_id uuid not null default gen_random_uuid(),
  match_id bigint not null references public.matches(id) on delete cascade,
  run_id text not null,
  attempt_status public.events_attempt_status not null,
  source_payload_count integer,
  normalized_count integer,
  stored_count integer,
  rejected_count integer,
  unmapped_provider_team_count integer,
  teamless_event_count integer,
  error text,
  details jsonb not null default '{}'::jsonb,
  claimed_at timestamptz not null default timezone('utc', now()),
  finished_at timestamptz,
  created_at timestamptz not null default timezone('utc', now())
);

alter table public.event_sync_attempts
  add column if not exists attempt_id uuid not null default gen_random_uuid(),
  add column if not exists unmapped_provider_team_count integer,
  add column if not exists teamless_event_count integer,
  add column if not exists claimed_at timestamptz not null default timezone('utc', now()),
  add column if not exists finished_at timestamptz;

create unique index if not exists event_sync_attempts_attempt_id_key
  on public.event_sync_attempts (attempt_id);

grant all on public.event_sync_attempts to service_role;
alter table public.event_sync_attempts enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
     where schemaname = 'public'
       and tablename = 'event_sync_attempts'
       and policyname = 'service role manages event sync attempts'
  ) then
    create policy "service role manages event sync attempts"
      on public.event_sync_attempts
      for all
      to service_role
      using (true)
      with check (true);
  end if;
end $$;

create index if not exists event_sync_attempts_match_idx
  on public.event_sync_attempts (match_id, created_at desc);

create index if not exists event_sync_attempts_open_idx
  on public.event_sync_attempts (match_id)
  where finished_at is null;

-- Operational coverage view. NOT granted to anon: public coverage is exposed
-- through the scoped api_*_v2 RPCs, which return only the numbers the UI needs.
--
-- Three independent axes, deliberately NOT collapsed into one boolean:
--   ingestion_resolved -> ingestion reached a definite answer (reconciled,
--                         provider_empty or unavailable). 'pending' is not resolved.
--   has_event_rows     -> reconciled AND events_stored_count > 0.
--   has_event_coverage -> event-derived metrics/plots may be computed.
--                         Equals has_event_rows. provider_empty is resolved but
--                         NOT covered; unavailable is resolved but NOT covered.
create or replace view public.match_event_coverage as
select
  m.id                          as match_id,
  m.season_id,
  m.league_id,
  m.home_team_id,
  m.away_team_id,
  m.status                      as match_status,
  m.kickoff_at,
  m.events_data_status,
  m.events_last_attempt_status,
  m.events_source_payload_count,
  m.events_stored_count,
  m.events_synced_at,
  m.events_last_attempt_at,
  m.events_empty_confirmations,
  m.events_next_retry_at,
  m.events_sync_error,
  (m.events_data_status in ('reconciled', 'provider_empty', 'unavailable')) as ingestion_resolved,
  (m.events_data_status = 'reconciled' and coalesce(m.events_stored_count, 0) > 0) as has_event_rows,
  (m.events_data_status = 'reconciled' and coalesce(m.events_stored_count, 0) > 0) as has_event_coverage,
  (m.events_data_status = 'provider_empty')                  as provider_confirmed_empty,
  (m.events_data_status = 'unavailable')                     as events_unavailable,
  (m.events_next_retry_at is not null and m.events_next_retry_at <= now()) as retry_due,
  (m.events_last_attempt_status in ('failed', 'count_mismatch')) as last_refresh_failed
from public.matches m;

revoke all on public.match_event_coverage from public, anon, authenticated;
grant select on public.match_event_coverage to service_role;
-- Uncomment only if an authenticated internal ops view is required:
-- grant select on public.match_event_coverage to authenticated;

commit;
