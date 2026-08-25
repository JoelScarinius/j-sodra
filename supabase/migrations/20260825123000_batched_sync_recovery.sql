-- Resumable event batching: close expired attempts and abandoned sync runs.
begin;

create or replace function public.release_stale_event_claims()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_released integer;
begin
  -- Close the exact open attempts whose match lease has expired.
  update public.event_sync_attempts a
     set attempt_status = 'failed',
         error = coalesce(a.error, 'claim lease expired'),
         finished_at = now()
    from public.matches m
   where a.match_id = m.id
     and a.run_id = m.events_sync_run_id
     and a.finished_at is null
     and m.events_last_attempt_status = 'in_progress'
     and m.events_claim_expires_at is not null
     and m.events_claim_expires_at < now();

  update public.matches m
     set events_last_attempt_status = 'failed',
         events_sync_error = 'claim lease expired',
         events_claim_expires_at = null,
         events_sync_run_id = null,
         events_next_retry_at = now()
   where m.events_last_attempt_status = 'in_progress'
     and m.events_claim_expires_at is not null
     and m.events_claim_expires_at < now();

  get diagnostics v_released = row_count;
  return v_released;
end;
$$;

create or replace function public.settle_stale_sync_runs(
  p_stale_after interval default interval '20 minutes'
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated integer;
begin
  if p_stale_after is null or p_stale_after <= interval '0 seconds' then
    raise exception 'settle_stale_sync_runs: p_stale_after must be positive'
      using errcode = '22023';
  end if;

  update public.sync_runs r
     set status = 'failed',
         finished_at = now(),
         error = coalesce(r.error, 'worker stopped before completing the run')
   where r.status = 'running'
     and r.started_at < now() - p_stale_after
     and not exists (
       select 1
         from public.matches m
        where m.events_sync_run_id = r.id::text
          and m.events_last_attempt_status = 'in_progress'
          and m.events_claim_expires_at >= now()
     );

  get diagnostics v_updated = row_count;
  return v_updated;
end;
$$;

create or replace function public.abandon_sync_run(
  p_run_id uuid,
  p_reason text default 'worker stopped before completing the run'
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_released integer;
begin
  if p_run_id is null then
    raise exception 'abandon_sync_run: p_run_id is required' using errcode = '22023';
  end if;

  update public.event_sync_attempts a
     set attempt_status = 'failed',
         error = left(coalesce(p_reason, 'run abandoned'), 2000),
         finished_at = now()
   where a.run_id = p_run_id::text
     and a.finished_at is null;

  update public.matches m
     set events_last_attempt_status = 'failed',
         events_sync_error = left(coalesce(p_reason, 'run abandoned'), 2000),
         events_claim_expires_at = null,
         events_sync_run_id = null,
         events_next_retry_at = now()
   where m.events_sync_run_id = p_run_id::text;
  get diagnostics v_released = row_count;

  update public.sync_runs r
     set status = 'failed',
         finished_at = now(),
         error = left(coalesce(p_reason, 'run abandoned'), 2000)
   where r.id = p_run_id
     and r.status = 'running';

  return v_released;
end;
$$;

revoke all on function public.release_stale_event_claims() from public, anon, authenticated;
revoke all on function public.settle_stale_sync_runs(interval) from public, anon, authenticated;
revoke all on function public.abandon_sync_run(uuid, text) from public, anon, authenticated;
grant execute on function public.release_stale_event_claims() to service_role;
grant execute on function public.settle_stale_sync_runs(interval) to service_role;
grant execute on function public.abandon_sync_run(uuid, text) to service_role;

commit;
