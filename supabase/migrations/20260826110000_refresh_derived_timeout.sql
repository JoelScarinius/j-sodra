begin;

-- refresh_season_derived_data is called through PostgREST by the service-role
-- Edge Function. Give this recurring RPC enough time to rebuild a season.
do $$
declare
  fn record;
begin
  for fn in
    select p.oid::regprocedure as signature
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'refresh_season_derived_data'
  loop
    execute format(
      'alter function %s set statement_timeout = %L',
      fn.signature,
      '60s'
    );
  end loop;
end;
$$;

notify pgrst, 'reload schema';
commit;
