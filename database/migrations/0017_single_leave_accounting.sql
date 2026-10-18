begin;

-- Older installations deducted approved leave immediately. The current workflow
-- reserves it in leave_holds until HR reconciles the official balance.
do $$
begin
  if exists (
    select 1 from pg_trigger
    where tgrelid = 'public.hr_requests'::regclass
      and tgname = 'hr_requests_deduct_vacation_days'
      and not tgisinternal
  ) then
    alter table public.hr_requests disable trigger hr_requests_deduct_vacation_days;
  end if;
end;
$$;

commit;
