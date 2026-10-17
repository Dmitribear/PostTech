-- Run only in a disposable test database after migrations and demo seed.
\set ON_ERROR_STOP on
begin;
grant usage on schema public to service_role, anon, authenticated;
grant select, update on public.employee_profiles to service_role;
grant select on public.employee_role_changes to anon, authenticated;

set local role service_role;
do $$
declare
    admin_id uuid := (select id from public.employee_profiles where email = 'hr@posttech.demo');
    worker_id uuid := (select id from public.employee_profiles where email = 'employee@posttech.demo');
    manager_id uuid := (select id from public.employee_profiles where email = 'manager@posttech.demo');
    original_name text := (select full_name from public.employee_profiles where id = worker_id);
    result record;
begin
    begin
        perform public.assign_employee_role(worker_id, worker_id, 'hr_admin');
        raise exception 'Worker was able to grant themselves HR privileges';
    exception when insufficient_privilege then null;
    end;
    begin
        perform public.assign_employee_role(admin_id, admin_id, 'worker');
        raise exception 'Administrator was able to remove their own role';
    exception when sqlstate 'PT409' then null;
    end;
    begin
        perform public.assign_employee_role(admin_id, manager_id, 'worker');
        raise exception 'Supervisor was demoted while still having direct reports';
    exception when sqlstate 'PT412' then null;
    end;
    begin
        perform public.assign_employee_role(admin_id, 'ffffffff-ffff-4fff-8fff-ffffffffffff', 'worker');
        raise exception 'Missing employee was not rejected';
    exception when no_data_found then null;
    end;
    select * into result from public.assign_employee_role(admin_id, worker_id, 'manager');
    assert result.previous_role = 'worker' and result.role = 'manager';
    assert (select role from public.employee_profiles where id = worker_id) = 'manager';
    assert (select full_name from public.employee_profiles where id = worker_id) = original_name;
    assert (select count(*) from public.employee_role_changes) = 1;
    assert exists (select 1 from public.employee_role_changes
        where employee_id = worker_id and changed_by = admin_id
          and previous_role = 'worker' and new_role = 'manager');
    perform public.assign_employee_role(admin_id, worker_id, 'manager');
    assert (select count(*) from public.employee_role_changes) = 1, 'No-op created duplicate audit events';
end $$;
reset role;

-- An audit write failure must also roll back the role update.
alter table public.employee_role_changes add constraint test_audit_failure check (new_role <> 'director');
set local role service_role;
do $$
declare
    admin_id uuid := (select id from public.employee_profiles where email = 'hr@posttech.demo');
    worker_id uuid := (select id from public.employee_profiles where email = 'employee@posttech.demo');
begin
    begin
        perform public.assign_employee_role(admin_id, worker_id, 'director');
        raise exception 'Expected audit failure';
    exception when check_violation then null;
    end;
    assert (select role from public.employee_profiles where id = worker_id) = 'manager';
    assert (select count(*) from public.employee_role_changes) = 1;
end $$;
reset role;

-- Neither unauthenticated nor logged-in browser callers may spoof the actor.
set local role anon;
do $$ begin
    assert (select count(*) from public.employee_role_changes) = 0;
    begin
        perform public.assign_employee_role(gen_random_uuid(), gen_random_uuid(), 'hr_admin');
        raise exception 'Anonymous caller executed role RPC';
    exception when insufficient_privilege then null;
    end;
end $$;
reset role;
set local role authenticated;
do $$ begin
    assert (select count(*) from public.employee_role_changes) = 0;
    begin
        perform public.assign_employee_role(gen_random_uuid(), gen_random_uuid(), 'hr_admin');
        raise exception 'Authenticated browser caller executed role RPC';
    exception when insufficient_privilege then null;
    end;
end $$;
reset role;
rollback;
select 'Role assignment, permissions, audit rollback, and RLS passed' as result;
