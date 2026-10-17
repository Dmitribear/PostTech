-- Apply after 0003. HR administrators manage access roles, not official HR data.
begin;

create table if not exists public.employee_role_changes (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid references public.employee_profiles(id) on delete set null,
    changed_by uuid references public.employee_profiles(id) on delete set null,
    previous_role public.app_role not null,
    new_role public.app_role not null,
    changed_at timestamptz not null default clock_timestamp()
);
create index if not exists employee_role_changes_employee_idx
    on public.employee_role_changes(employee_id, changed_at desc);
alter table public.employee_role_changes enable row level security;
grant select, insert on public.employee_role_changes to service_role;

create or replace function public.assign_employee_role(
    p_actor_id uuid,
    p_employee_id uuid,
    p_role public.app_role
)
returns table (employee_id uuid, previous_role public.app_role, role public.app_role)
language plpgsql
security invoker
set search_path = ''
as $$
declare
    actor_role public.app_role;
    existing_role public.app_role;
begin
    -- Shared by every role mutation. Recheck the actor AFTER taking the lock:
    -- otherwise two administrators could demote each other using stale rights.
    perform pg_catalog.pg_advisory_xact_lock(734021, 1);
    select e.role into actor_role from public.employee_profiles e
    where e.id = p_actor_id for update;
    if not found or actor_role <> 'hr_admin' then
        raise exception using errcode = '42501', message = 'HR administrator role required';
    end if;
    if p_role is null then
        raise exception using errcode = '22004', message = 'Role is required';
    end if;
    select e.role into existing_role from public.employee_profiles e
    where e.id = p_employee_id for update;
    if not found then
        raise exception using errcode = 'P0002', message = 'Employee not found';
    end if;
    if p_actor_id = p_employee_id and p_role <> 'hr_admin' then
        raise exception using errcode = 'PT409', message = 'Cannot remove own administrator role';
    end if;
    if existing_role = p_role then
        return query select p_employee_id, existing_role, p_role;
        return;
    end if;
    if p_role not in ('manager', 'director') and exists (
        select 1 from public.employee_profiles e where e.manager_id = p_employee_id
    ) then
        raise exception using errcode = 'PT412', message = 'Reassign direct reports first';
    end if;

    update public.employee_profiles e set role = p_role where e.id = p_employee_id;
    insert into public.employee_role_changes (employee_id, changed_by, previous_role, new_role)
    values (p_employee_id, p_actor_id, existing_role, p_role);
    return query select p_employee_id, existing_role, p_role;
end;
$$;

-- The actor argument is supplied by FastAPI after token validation. Browser
-- clients must never be able to call this RPC with a forged administrator ID.
revoke all on function public.assign_employee_role(uuid, uuid, public.app_role)
    from public, anon, authenticated;
grant execute on function public.assign_employee_role(uuid, uuid, public.app_role)
    to service_role;

commit;
