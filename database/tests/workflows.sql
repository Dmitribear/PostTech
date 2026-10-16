\set ON_ERROR_STOP on
begin;

-- Deliberately fail a notification write to verify transaction rollback.
create function public.test_reject_notification() returns trigger language plpgsql as $$
begin
    if new.notification_type = current_setting('posttech.test_failure', true)
       or (current_setting('posttech.test_failure', true) = 'manager_completion'
           and new.notification_type = 'course_completed'
           and exists (select 1 from public.employee_profiles where id = new.employee_id and role = 'manager')) then
        raise exception using errcode = 'ZX001', message = 'Simulated notification failure';
    end if;
    return new;
end $$;
create trigger test_reject_notification before insert on public.notifications
for each row execute function public.test_reject_notification();

-- Match the existing Supabase application-table grants; execute as its API role.
grant usage on schema public to service_role, anon, authenticated;
grant all on all tables in schema public to service_role;
set local role service_role;
do $$
<<scenario>>
declare
    worker uuid := (select id from public.employee_profiles where role = 'worker' limit 1);
    manager uuid := (select id from public.employee_profiles where role = 'manager' limit 1);
    request_id uuid;
    assignment_id uuid;
    course_id uuid;
    before_count integer;
    affected integer;
begin
    -- A failed creation must leave neither a request nor an event behind.
    select count(*) into before_count from public.hr_requests;
    perform set_config('posttech.test_failure', 'request_created', true);
    begin
        insert into public.hr_requests (employee_id, request_type, amount)
        values (worker, 'advance', 1200);
        raise exception 'Expected notification failure';
    exception when sqlstate 'ZX001' then null;
    end;
    assert (select count(*) from public.hr_requests) = before_count, 'Request persisted after notification failure';
    perform set_config('posttech.test_failure', '', true);

    insert into public.hr_requests (employee_id, request_type, amount)
    values (worker, 'advance', 1200) returning id into request_id;
    assert (select count(*) from public.hr_request_events e where e.request_id = scenario.request_id) = 1;
    assert (select count(*) from public.notifications n where n.request_id = scenario.request_id and n.employee_id = manager) = 1;

    -- Review failure must preserve pending status and its original history.
    perform set_config('posttech.test_failure', 'request_status_changed', true);
    begin
        update public.hr_requests r set status = 'approved', reviewed_by = manager, reviewed_at = now()
        where r.id = request_id and r.status = 'pending';
        raise exception 'Expected review notification failure';
    exception when sqlstate 'ZX001' then null;
    end;
    assert (select status from public.hr_requests where id = request_id) = 'pending';
    assert (select count(*) from public.hr_request_events e where e.request_id = scenario.request_id) = 1;
    perform set_config('posttech.test_failure', '', true);

    update public.hr_requests r set status = 'approved', reviewed_by = manager, reviewed_at = now()
    where r.id = request_id and r.status = 'pending';
    assert (select count(*) from public.hr_request_events e where e.request_id = scenario.request_id) = 2;
    assert exists (select 1 from public.hr_request_events e where e.request_id = scenario.request_id
                   and old_status = 'pending' and new_status = 'approved' and actor_id = manager);
    assert (select count(*) from public.notifications n where n.request_id = scenario.request_id and n.employee_id = worker) = 1;
    update public.hr_requests r set status = 'rejected' where r.id = request_id and r.status = 'pending';
    get diagnostics affected = row_count;
    assert affected = 0, 'Review conditional write overwrote an existing decision';

    -- Course assignment and its notification must also commit together.
    insert into public.courses (title, description, material_markdown)
    values ('Transaction test', 'Test', 'Test') returning id into course_id;
    perform set_config('posttech.test_failure', 'course_assigned', true);
    begin
        insert into public.course_assignments (employee_id, course_id, assigned_by)
        values (worker, course_id, manager);
        raise exception 'Expected assignment notification failure';
    exception when sqlstate 'ZX001' then null;
    end;
    assert not exists (select 1 from public.course_assignments a where a.course_id = scenario.course_id);
    perform set_config('posttech.test_failure', '', true);
    insert into public.course_assignments (employee_id, course_id, assigned_by)
    values (worker, course_id, manager) returning id into assignment_id;

    -- Fail the manager notification AFTER the learner notification was inserted.
    select count(*) into before_count from public.notifications;
    perform set_config('posttech.test_failure', 'manager_completion', true);
    begin
        update public.course_assignments set status = 'completed', progress_percent = 100,
            score_percent = 100, completed_at = now() where id = assignment_id and status <> 'completed';
        raise exception 'Expected completion notification failure';
    exception when sqlstate 'ZX001' then null;
    end;
    assert (select status from public.course_assignments where id = assignment_id) = 'not_started';
    assert (select count(*) from public.notifications) = before_count, 'Learner notification escaped rollback';
    perform set_config('posttech.test_failure', '', true);
    update public.course_assignments set status = 'completed', progress_percent = 100,
        score_percent = 100, completed_at = now() where id = assignment_id and status <> 'completed';
    assert (select count(*) from public.notifications) = before_count + 2;
    assert exists (select 1 from public.notifications where employee_id = worker and notification_type = 'course_completed');
    assert exists (select 1 from public.notifications where employee_id = manager and notification_type = 'course_completed');
    update public.course_assignments set score_percent = 0 where id = assignment_id and status <> 'completed';
    get diagnostics affected = row_count;
    assert affected = 0;
    assert (select score_percent from public.course_assignments where id = assignment_id) = 100;
    assert (select count(*) from public.notifications) = before_count + 2;

    -- Completion without a manager still notifies the learner.
    update public.employee_profiles set manager_id = null where id = worker;
    insert into public.courses (title, description, material_markdown)
    values ('No manager test', 'Test', 'Test') returning id into course_id;
    insert into public.course_assignments (employee_id, course_id) values (worker, course_id)
    returning id into assignment_id;
    select count(*) into before_count from public.notifications;
    update public.course_assignments set status = 'completed', progress_percent = 100,
        score_percent = 50, completed_at = now() where id = assignment_id;
    assert (select count(*) from public.notifications) = before_count + 1;
end $$;
reset role;

-- RLS blocks direct browser access even if the table privilege is granted.
grant select on public.hr_request_events to anon, authenticated;
set local role anon;
do $$ begin assert (select count(*) from public.hr_request_events) = 0; end $$;
reset role;
set local role authenticated;
do $$ begin assert (select count(*) from public.hr_request_events) = 0; end $$;
reset role;

rollback;
select 'Atomic workflows, history, notification rollback, completion, and RLS passed' as result;
