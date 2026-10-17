-- Run only in a disposable test database after all migrations and demo seed.
\set ON_ERROR_STOP on
begin;

do $$
declare
    worker_id uuid := (select id from public.employee_profiles where email = 'employee@posttech.demo');
    balance_before numeric(5, 1);
    request_id uuid;
    request_days integer;
begin
    select vacation_days_remaining into balance_before
    from public.employee_profiles where id = worker_id;

    insert into public.hr_requests (
        employee_id, request_type, status, start_date, end_date, comment
    ) values (
        worker_id, 'leave', 'pending', date '2026-12-10', date '2026-12-12', 'vacation-balance integration test'
    ) returning id, leave_days into request_id, request_days;
    assert request_days = 3, 'Leave days must count both date endpoints';
    assert (select vacation_days_remaining from public.employee_profiles where id = worker_id) = balance_before,
        'Pending request must not deduct days';

    update public.hr_requests set status = 'pending_hr' where id = request_id;
    assert (select vacation_days_remaining from public.employee_profiles where id = worker_id) = balance_before,
        'Intermediate review must not deduct days';

    update public.hr_requests set status = 'approved' where id = request_id;
    assert (select vacation_days_remaining from public.employee_profiles where id = worker_id) = balance_before - 3,
        'Final approval must deduct inclusive calendar days';
    update public.hr_requests set status = 'approved' where id = request_id;
    assert (select vacation_days_remaining from public.employee_profiles where id = worker_id) = balance_before - 3,
        'Repeating an unchanged approved status must not deduct twice';

    update public.employee_profiles set vacation_days_remaining = 2 where id = worker_id;
    insert into public.hr_requests (
        employee_id, request_type, status, start_date, end_date, comment
    ) values (
        worker_id, 'leave', 'pending_hr', date '2027-01-10', date '2027-01-12', 'insufficient-balance integration test'
    ) returning id into request_id;
    begin
        update public.hr_requests set status = 'approved' where id = request_id;
        raise exception 'Expected insufficient-balance rejection';
    exception when sqlstate 'PT413' then null;
    end;
    assert (select status from public.hr_requests where id = request_id) = 'pending_hr',
        'Failed approval must leave the request pending HR';
    assert (select vacation_days_remaining from public.employee_profiles where id = worker_id) = 2,
        'Failed approval must preserve the balance';

    insert into public.hr_requests (employee_id, request_type, status, amount, comment)
    values (worker_id, 'advance', 'pending_hr', 100, 'advance balance integration test')
    returning id into request_id;
    update public.hr_requests set status = 'approved' where id = request_id;
    assert (select vacation_days_remaining from public.employee_profiles where id = worker_id) = 2,
        'Approving an advance must not change vacation balance';
end $$;

rollback;
select 'Vacation duration, approval deduction, and insufficient-balance rollback passed' as result;