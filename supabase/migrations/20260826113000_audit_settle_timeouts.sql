begin;

do $$
declare
  fn record;
begin
  for fn in
    select p.oid::regprocedure as signature
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname in (
        'run_completeness_audit',
        'settle_provider_empty_matches'
      )
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
