-- Count leave requests in inclusive calendar days and deduct only on final approval.
alter table public.hr_requests
    add column if not exists leave_days integer generated always as (
        case
            when request_type = 'leave' then end_date - start_date + 1
            else null
        end
    ) stored;

create or replace function public.deduct_approved_leave_days()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    -- This trigger runs in the same transaction as the final status change.
    -- The conditional UPDATE serializes concurrent approvals on the employee row.
    update public.employee_profiles as employee
    set vacation_days_remaining = employee.vacation_days_remaining - new.leave_days
    where employee.id = new.employee_id
      and employee.vacation_days_remaining >= new.leave_days;

    if not found then
        raise exception using
            errcode = 'PT413',
            message = 'Insufficient vacation balance';
    end if;

    return new;
end;
$$;

do $$
begin
    if not exists (
        select 1
        from pg_catalog.pg_trigger
        where tgname = 'hr_requests_deduct_vacation_days'
          and tgrelid = 'public.hr_requests'::regclass
          and not tgisinternal
    ) then
        execute $trigger$
            create trigger hr_requests_deduct_vacation_days
            after update of status on public.hr_requests
            for each row
            when (
                old.status is distinct from new.status
                and new.status = 'approved'
                and new.request_type = 'leave'
            )
            execute function public.deduct_approved_leave_days()
        $trigger$;
    end if;
end;
$$;