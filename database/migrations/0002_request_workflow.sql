-- Apply after 0001_digital_hr.sql. Existing requests receive history below.
-- Each RPC runs in the caller's transaction; any event/notification failure
-- rolls back the request mutation as well. Only the trusted API may call it.
begin;

alter table public.hr_requests add column idempotency_key uuid;
alter table public.hr_requests
    add constraint hr_requests_employee_idempotency_key
    unique (employee_id, idempotency_key);

create table public.request_events (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null references public.hr_requests(id) on delete cascade,
    actor_id uuid references public.employee_profiles(id) on delete set null,
    event_type text not null check (event_type in ('created', 'approved', 'rejected')),
    from_status public.hr_request_status,
    to_status public.hr_request_status not null,
    comment text not null default '',
    created_at timestamptz not null default now(),
    unique (request_id, event_type),
    constraint request_event_transition_valid check (
        (event_type = 'created' and from_status is null and to_status = 'pending')
        or (
            event_type in ('approved', 'rejected')
            and from_status is not null and from_status = 'pending'
            and to_status::text = event_type
        )
    )
);

create index request_events_request_created_idx
    on public.request_events(request_id, created_at, id);

alter table public.request_events enable row level security;
revoke all on table public.request_events from public, anon, authenticated;
-- SECURITY INVOKER uses the caller's table privileges. Grant them explicitly
-- rather than depending on a Supabase project's default privileges.
grant usage on schema public to service_role;
grant select on table public.employee_profiles to service_role;
grant select, insert, update on table public.hr_requests, public.notifications to service_role;
grant select, insert on table public.request_events to service_role;

-- Reconstruct only transitions evidenced by the existing request row.
-- No notifications are generated for historical data.
insert into public.request_events (
    request_id, actor_id, event_type, from_status, to_status, comment, created_at
)
select id, employee_id, 'created', null, 'pending', comment, created_at
from public.hr_requests;

insert into public.request_events (
    request_id, actor_id, event_type, from_status, to_status, comment, created_at
)
select id, reviewed_by, status::text, 'pending', status,
       coalesce(reviewer_comment, ''), coalesce(reviewed_at, updated_at, created_at)
from public.hr_requests
where status in ('approved', 'rejected');

create function public.create_hr_request(
    p_actor_id uuid,
    p_request_type public.hr_request_type,
    p_start_date date,
    p_end_date date,
    p_amount numeric,
    p_comment text,
    p_idempotency_key uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    v_actor public.employee_profiles%rowtype;
    v_request public.hr_requests%rowtype;
    v_manager_id uuid;
    v_comment text := coalesce(p_comment, '');
begin
    if p_idempotency_key is null then
        raise exception using errcode = 'PT422', message = 'Idempotency key is required';
    end if;
    if char_length(v_comment) > 2000 then
        raise exception using errcode = 'PT422', message = 'Comment must not exceed 2000 characters';
    end if;
    if p_request_type is null then
        raise exception using errcode = 'PT422', message = 'Request type is required';
    end if;

    if p_request_type = 'leave' then
        if p_start_date is null or p_end_date is null
            or not isfinite(p_start_date) or not isfinite(p_end_date)
            or p_end_date < p_start_date or p_amount is not null then
            raise exception using errcode = 'PT422', message = 'Leave requests require a valid date range and no amount';
        end if;
    else
        -- Reject precision that numeric(12, 2) would silently round; comparing
        -- retries to the stored payload must not change the submitted amount.
        if p_amount is null or p_amount <= 0 or p_amount > 1000000
            or p_amount <> round(p_amount, 2)
            or p_start_date is not null or p_end_date is not null then
            raise exception using errcode = 'PT422', message = 'Advance requests require an amount from 0.01 to 1000000 with at most two decimal places and no dates';
        end if;
    end if;

    if p_actor_id is null then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;

    -- Serialize only retries for this employee/key. Hash collisions can only
    -- delay an unrelated request; the unique constraint remains authoritative.
    perform pg_advisory_xact_lock(
        hashtextextended('hr-request:' || p_actor_id::text || ':' || p_idempotency_key::text, 0)
    );

    select * into v_actor
    from public.employee_profiles
    where id = p_actor_id;
    if not found then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;

    select * into v_request
    from public.hr_requests
    where employee_id = p_actor_id and idempotency_key = p_idempotency_key;
    if found then
        if v_request.request_type is distinct from p_request_type
            or v_request.start_date is distinct from p_start_date
            or v_request.end_date is distinct from p_end_date
            or v_request.amount is distinct from p_amount
            or v_request.comment is distinct from v_comment then
            raise exception using errcode = 'PT409', message = 'Idempotency key was already used with a different request';
        end if;
        return to_jsonb(v_request) - 'idempotency_key';
    end if;

    insert into public.hr_requests (
        employee_id, request_type, start_date, end_date, amount, comment, idempotency_key
    ) values (
        p_actor_id, p_request_type, p_start_date, p_end_date, p_amount, v_comment, p_idempotency_key
    )
    returning * into v_request;

    insert into public.request_events (
        request_id, actor_id, event_type, from_status, to_status, comment, created_at
    ) values (
        v_request.id, p_actor_id, 'created', null, 'pending', v_comment, v_request.created_at
    );

    select id into v_manager_id
    from public.employee_profiles
    where id = v_actor.manager_id
        and id <> p_actor_id
        and role in ('manager', 'hr_admin');

    if v_manager_id is not null then
        insert into public.notifications (
            employee_id, request_id, notification_type, title, body
        ) values (
            v_manager_id, v_request.id, 'request_created', 'Новая заявка сотрудника',
            format('%s создал(а) заявку: %s.', v_actor.full_name, p_request_type)
        );
    else
        insert into public.notifications (
            employee_id, request_id, notification_type, title, body
        )
        select id, v_request.id, 'request_created', 'Новая заявка сотрудника',
               format('%s создал(а) заявку: %s.', v_actor.full_name, p_request_type)
        from public.employee_profiles
        where role = 'hr_admin';
    end if;

    return to_jsonb(v_request) - 'idempotency_key';
end;
$$;

create function public.review_hr_request(
    p_actor_id uuid,
    p_request_id uuid,
    p_status public.hr_request_status,
    p_reviewer_comment text
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    v_actor public.employee_profiles%rowtype;
    v_employee public.employee_profiles%rowtype;
    v_request public.hr_requests%rowtype;
    v_comment text := coalesce(p_reviewer_comment, '');
begin
    if p_status is null or p_status not in ('approved', 'rejected') then
        raise exception using errcode = 'PT422', message = 'Review status must be approved or rejected';
    end if;
    if char_length(v_comment) > 2000 then
        raise exception using errcode = 'PT422', message = 'Reviewer comment must not exceed 2000 characters';
    end if;

    -- The lock makes concurrent decisions observe the committed winning review.
    -- Re-read authorization after waiting, including when replaying a decision.
    select * into v_request
    from public.hr_requests
    where id = p_request_id
    for update;
    if not found then
        raise exception using errcode = 'PT404', message = 'Request not found';
    end if;

    select * into v_actor
    from public.employee_profiles
    where id = p_actor_id;
    if not found then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;
    if v_actor.role not in ('manager', 'hr_admin') then
        raise exception using errcode = 'PT403', message = 'Reviewer role required';
    end if;
    if v_request.employee_id = p_actor_id then
        raise exception using errcode = 'PT403', message = 'You cannot review your own request';
    end if;

    select * into v_employee
    from public.employee_profiles
    where id = v_request.employee_id;
    if not found then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;
    if v_actor.role <> 'hr_admin' and v_employee.manager_id is distinct from p_actor_id then
        raise exception using errcode = 'PT403', message = 'You cannot manage this employee';
    end if;

    if v_request.status <> 'pending' then
        if v_request.status = p_status
            and v_request.reviewed_by = p_actor_id
            and coalesce(v_request.reviewer_comment, '') = v_comment then
            return to_jsonb(v_request) - 'idempotency_key';
        end if;
        raise exception using errcode = 'PT409', message = 'Request was already reviewed';
    end if;

    update public.hr_requests
    set status = p_status,
        reviewer_comment = p_reviewer_comment,
        reviewed_by = p_actor_id,
        reviewed_at = now()
    where id = p_request_id
    returning * into v_request;

    insert into public.request_events (
        request_id, actor_id, event_type, from_status, to_status, comment, created_at
    ) values (
        p_request_id, p_actor_id, p_status::text, 'pending', p_status,
        v_comment, v_request.reviewed_at
    );

    insert into public.notifications (
        employee_id, request_id, notification_type, title, body
    ) values (
        v_request.employee_id, p_request_id, 'request_status_changed', 'Статус заявки изменён',
        format('Ваша заявка получила статус: %s.', p_status)
    );

    return to_jsonb(v_request) - 'idempotency_key';
end;
$$;

revoke execute on function public.create_hr_request(
    uuid, public.hr_request_type, date, date, numeric, text, uuid
) from public, anon, authenticated;
grant execute on function public.create_hr_request(
    uuid, public.hr_request_type, date, date, numeric, text, uuid
) to service_role;

revoke execute on function public.review_hr_request(
    uuid, uuid, public.hr_request_status, text
) from public, anon, authenticated;
grant execute on function public.review_hr_request(
    uuid, uuid, public.hr_request_status, text
) to service_role;

notify pgrst, 'reload schema';
commit;
