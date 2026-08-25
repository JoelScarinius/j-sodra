-- Give the trusted backend role access to the warehouse objects used by
-- sync-league. Frontend roles are not granted direct write access.

begin;

grant usage on schema public to service_role;

grant select, insert, update, delete on table
  public.leagues,
  public.seasons,
  public.teams,
  public.season_teams,
  public.matches,
  public.team_match_stats,
  public.standings,
  public.aggregated_team_stats,
  public.events,
  public.sync_runs,
  public.sync_cursors,
  public.event_sync_attempts
to service_role;

grant usage, select on all sequences in schema public
to service_role;

-- Ensure future tables and identity sequences created by this migration
-- owner remain available to the trusted backend role.
alter default privileges in schema public
  grant select, insert, update, delete on tables to service_role;

alter default privileges in schema public
  grant usage, select on sequences to service_role;

commit;