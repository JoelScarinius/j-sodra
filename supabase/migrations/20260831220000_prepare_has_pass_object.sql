begin;

alter table public.events
  add column if not exists has_pass_object boolean;

create or replace function public.populate_event_analysis_fields()
returns trigger
language plpgsql
set search_path = public
as $function$
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

  new.has_pass_object := case
    when jsonb_typeof(new.payload -> 'pass') = 'object' then true
    else null
  end;

  if new.has_pass_object is true then
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
$function$;

create or replace function public.backfill_event_has_pass_object_batch(
  p_match_limit integer default 5
)
returns table (
  matches_processed integer,
  rows_updated integer,
  remaining_rows bigint
)
language plpgsql
security definer
set search_path = public
set statement_timeout = '60s'
as $function$
declare
  v_match_ids bigint[];
  v_matches integer := 0;
  v_updated integer := 0;
begin
  if p_match_limit is null or p_match_limit < 1 or p_match_limit > 20 then
    raise exception 'p_match_limit must be between 1 and 20'
      using errcode = '22023';
  end if;

  select array_agg(match_id order by match_id)
    into v_match_ids
  from (
    select distinct e.match_id
    from public.events e
    where e.has_pass_object is null
      and jsonb_typeof(e.payload -> 'pass') = 'object'
    order by e.match_id
    limit p_match_limit
  ) selected;

  v_matches := coalesce(cardinality(v_match_ids), 0);

  if v_matches > 0 then
    update public.events e
       set has_pass_object = true
     where e.match_id = any(v_match_ids)
       and e.has_pass_object is null
       and jsonb_typeof(e.payload -> 'pass') = 'object';
    get diagnostics v_updated = row_count;
  end if;

  return query
  select
    v_matches,
    v_updated,
    count(*)::bigint
  from public.events e
  where e.has_pass_object is null
    and jsonb_typeof(e.payload -> 'pass') = 'object';
end;
$function$;

revoke all on function public.backfill_event_has_pass_object_batch(integer)
  from public, anon, authenticated;
grant execute on function public.backfill_event_has_pass_object_batch(integer)
  to service_role, postgres;

notify pgrst, 'reload schema';
commit;
