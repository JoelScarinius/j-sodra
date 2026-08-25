begin;

create or replace function public.mark_match_event_unavailable(
  p_match_id bigint,
  p_run_id text,
  p_attempt_id uuid,
  p_reason text,
  p_retry_after interval default interval '7 days'
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_match_id is null
     or nullif(btrim(p_run_id), '') is null
     or p_attempt_id is null
     or p_retry_after is null
     or p_retry_after <= interval '0 seconds' then
    raise exception
      'mark_match_event_unavailable: match, run, attempt and a positive retry interval are required'
      using errcode = '22023';
  end if;

  update public.event_sync_attempts a
     set attempt_status = 'succeeded',
         error = p_reason,
         finished_at = now()
   where a.attempt_id = p_attempt_id
     and a.match_id = p_match_id
     and a.run_id = p_run_id
     and a.finished_at is null;

  if not found then
    raise exception
      'mark_match_event_unavailable: open attempt not found'
      using errcode = '55006';
  end if;

  update public.matches m
     set events_data_status = 'unavailable',
         events_last_attempt_status = 'succeeded',
         events_next_retry_at = now() + p_retry_after,
         events_sync_error = p_reason,
         events_stored_count = null,
         events_source_payload_count = null,
         events_claim_expires_at = null,
         events_sync_run_id = null,
         updated_at = now()
   where m.id = p_match_id
     and m.events_sync_run_id = p_run_id;

  if not found then
    raise exception
      'mark_match_event_unavailable: claimed match not found'
      using errcode = '55006';
  end if;
end;
$$;

revoke all on function public.mark_match_event_unavailable(
  bigint,
  text,
  uuid,
  text,
  interval
) from public, anon, authenticated;

grant execute on function public.mark_match_event_unavailable(
  bigint,
  text,
  uuid,
  text,
  interval
) to service_role;

commit;