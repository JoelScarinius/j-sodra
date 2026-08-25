select *
from public.run_completeness_audit(
  array:bigint[]
)
where severity = 'blocker'
  and not passed
order by check_name;