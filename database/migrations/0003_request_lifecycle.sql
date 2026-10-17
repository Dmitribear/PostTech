-- Apply after 0002. This MVP counts inclusive calendar days, uses the employee's
-- Kazakhstan business date, and never changes the official 1C leave balance.
-- Existing RPC signatures are retained. Do not apply against a live database
-- without the normal deployment/migration procedure.
begin;

alter table public.hr_requests
    add column approval_route text not null default 'unassigned'
        check (approval_route in ('manager', 'hr', 'unassigned')),
    add column approver_ids uuid[] not null default '{}',
    add column approvers jsonb not null default '[]'::jsonb
        check (jsonb_typeof(approvers) = 'array'),
    add column cancelled_at timestamptz,
    add constraint hr_requests_no_self_approver check (not (employee_id = any(approver_ids)));

create index hr_requests_approver_ids_idx on public.hr_requests using gin (approver_ids);
create index hr_requests_active_leave_idx on public.hr_requests(employee_id, start_date, end_date)
    where request_type = 'leave' and status in ('pending', 'approved');

alter table public.request_events drop constraint request_events_event_type_check;
alter table public.request_events add constraint request_events_event_type_check
    check (event_type in ('created', 'approved', 'rejected', 'cancelled'));
alter table public.request_events drop constraint request_event_transition_valid;
alter table public.request_events add constraint request_event_transition_valid check (
    (event_type = 'created' and from_status is null and to_status = 'pending')
    or (event_type in ('approved', 'rejected', 'cancelled')
        and from_status is not null and from_status = 'pending' and to_status::text = event_type)
);

create function public.get_hr_request_routing(p_actor_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    v_actor public.employee_profiles%rowtype;
    v_manager public.employee_profiles%rowtype;
    v_route text := 'unassigned';
    v_approvers jsonb := '[]'::jsonb;
    v_cursor uuid;
    v_seen uuid[];
    v_cycle boolean := false;
begin
    select * into v_actor from public.employee_profiles where id = p_actor_id;
    if not found then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;

    -- A configured manager must actually be an eligible reviewer and belong to
    -- an acyclic reporting chain. A self link or cycle falls back to other HR.
    select * into v_manager from public.employee_profiles
    where id = v_actor.manager_id and id <> p_actor_id and role in ('manager', 'hr_admin');
    if found then
        v_cursor := v_manager.id;
        v_seen := array[p_actor_id];
        while v_cursor is not null loop
            if v_cursor = any(v_seen) then
                v_cycle := true;
                exit;
            end if;
            v_seen := array_append(v_seen, v_cursor);
            select manager_id into v_cursor from public.employee_profiles where id = v_cursor;
        end loop;
        if not v_cycle then
            v_route := 'manager';
            v_approvers := jsonb_build_array(jsonb_build_object(
                'id', v_manager.id, 'full_name', v_manager.full_name, 'role', v_manager.role
            ));
        end if;
    end if;

    if v_route = 'unassigned' then
        select coalesce(jsonb_agg(jsonb_build_object(
            'id', id, 'full_name', full_name, 'role', role
        ) order by full_name, id), '[]'::jsonb) into v_approvers
        from public.employee_profiles where role = 'hr_admin' and id <> p_actor_id;
        if jsonb_array_length(v_approvers) > 0 then v_route := 'hr'; end if;
    end if;

    return jsonb_build_object(
        'can_submit', v_route <> 'unassigned', 'route', v_route, 'approvers', v_approvers,
        'message', case when v_route = 'unassigned' then 'No eligible approver is configured; contact HR' else null end,
        'today', (current_timestamp at time zone 'Asia/Qyzylorda')::date,
        'policy', 'MVP: inclusive calendar days; no past start dates; pending and approved leave periods must not overlap; official leave balance is read-only.'
    );
end;
$$;

-- Pending legacy requests receive a route using the current organisation chart.
-- For closed requests only an evidenced reviewer is retained; no synthetic
-- events or notifications are added and unknown historical routes stay explicit.
with routes as (
    select id, public.get_hr_request_routing(employee_id) as route
    from public.hr_requests where status = 'pending'
)
update public.hr_requests r set
    approval_route = routes.route->>'route',
    approvers = routes.route->'approvers',
    approver_ids = array(select (person->>'id')::uuid from jsonb_array_elements(routes.route->'approvers') person)
from routes where r.id = routes.id;

update public.hr_requests r set
    approval_route = case when e.role = 'manager' then 'manager' else 'hr' end,
    approvers = jsonb_build_array(jsonb_build_object('id', e.id, 'full_name', e.full_name, 'role', e.role)),
    approver_ids = array[e.id]
from public.employee_profiles e
where r.status in ('approved', 'rejected') and r.reviewed_by = e.id
    and e.id <> r.employee_id and e.role in ('manager', 'hr_admin');

create or replace function public.create_hr_request(
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
    v_comment text := coalesce(p_comment, '');
    v_routing jsonb;
    v_approver_ids uuid[];
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
        if p_start_date is null or p_end_date is null or not isfinite(p_start_date)
            or not isfinite(p_end_date) or p_end_date < p_start_date or p_amount is not null then
            raise exception using errcode = 'PT422', message = 'Leave requests require a valid date range and no amount';
        end if;
    else
        if p_amount is null or p_amount <= 0 or p_amount > 1000000
            or p_amount <> round(p_amount, 2) or p_start_date is not null or p_end_date is not null then
            raise exception using errcode = 'PT422', message = 'Advance requests require an amount from 0.01 to 1000000 with at most two decimal places and no dates';
        end if;
    end if;

    -- Lock the employee, not only the idempotency key: different simultaneous
    -- keys must not create overlapping active leave. All creates for this owner
    -- serialize; reads below observe the preceding committed transaction.
    if p_actor_id is null then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;
    perform pg_advisory_xact_lock(hashtextextended('hr-request-owner:' || p_actor_id::text, 0));
    select * into v_actor from public.employee_profiles where id = p_actor_id;
    if not found then
        raise exception using errcode = 'PT404', message = 'Employee not found';
    end if;
    select * into v_request from public.hr_requests
    where employee_id = p_actor_id and idempotency_key = p_idempotency_key;
    if found then
        if v_request.request_type is distinct from p_request_type
            or v_request.start_date is distinct from p_start_date
            or v_request.end_date is distinct from p_end_date
            or v_request.amount is distinct from p_amount
            or v_request.comment is distinct from v_comment then
            raise exception using errcode = 'PT409', message = 'Idempotency key was already used with a different request';
        end if;
        -- A retry is an acknowledgement, not a new request. It must keep working
        -- after a date passes, a manager changes, or this request is cancelled.
        return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
    end if;

    if p_request_type = 'leave' then
        if p_start_date < (current_timestamp at time zone 'Asia/Qyzylorda')::date then
            raise exception using errcode = 'PT422', message = 'Leave cannot start in the past';
        end if;
        if exists (
            select 1 from public.hr_requests
            where employee_id = p_actor_id and request_type = 'leave'
                and status in ('pending', 'approved')
                and start_date <= p_end_date and end_date >= p_start_date
        ) then
            raise exception using errcode = 'PT409', message = 'Leave overlaps an existing pending or approved request';
        end if;
    end if;

    v_routing := public.get_hr_request_routing(p_actor_id);
    if not (v_routing->>'can_submit')::boolean then
        raise exception using errcode = 'PT409', message = 'No eligible approver is configured; contact HR';
    end if;
    v_approver_ids := array(select (person->>'id')::uuid from jsonb_array_elements(v_routing->'approvers') person);
    insert into public.hr_requests (
        employee_id, request_type, start_date, end_date, amount, comment, idempotency_key,
        approval_route, approver_ids, approvers
    ) values (
        p_actor_id, p_request_type, p_start_date, p_end_date, p_amount, v_comment, p_idempotency_key,
        v_routing->>'route', v_approver_ids, v_routing->'approvers'
    ) returning * into v_request;

    insert into public.request_events (
        request_id, actor_id, event_type, from_status, to_status, comment, created_at
    ) values (v_request.id, p_actor_id, 'created', null, 'pending', v_comment, v_request.created_at);
    insert into public.notifications (employee_id, request_id, notification_type, title, body)
    select id, v_request.id, 'request_created', 'Новая заявка на согласование',
        format('%s создал(а) заявку: %s.', v_actor.full_name, p_request_type)
    from public.employee_profiles where id = any(v_approver_ids) and id <> p_actor_id;
    return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
end;
$$;

create or replace function public.review_hr_request(
    p_actor_id uuid, p_request_id uuid, p_status public.hr_request_status, p_reviewer_comment text
)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    v_actor public.employee_profiles%rowtype;
    v_request public.hr_requests%rowtype;
    v_comment text := coalesce(p_reviewer_comment, '');
begin
    if p_status is null or p_status not in ('approved', 'rejected') then
        raise exception using errcode = 'PT422', message = 'Review status must be approved or rejected';
    end if;
    if char_length(v_comment) > 2000 then
        raise exception using errcode = 'PT422', message = 'Reviewer comment must not exceed 2000 characters';
    end if;
    if p_status = 'rejected' and v_comment !~ '[^[:space:]]' then
        raise exception using errcode = 'PT422', message = 'A reason is required to reject a request';
    end if;

    select * into v_request from public.hr_requests where id = p_request_id for update;
    if not found then raise exception using errcode = 'PT404', message = 'Request not found'; end if;
    select * into v_actor from public.employee_profiles where id = p_actor_id;
    if not found then raise exception using errcode = 'PT404', message = 'Employee not found'; end if;
    if v_actor.role not in ('manager', 'hr_admin') then
        raise exception using errcode = 'PT403', message = 'Reviewer role required';
    end if;
    if v_request.employee_id = p_actor_id then
        raise exception using errcode = 'PT403', message = 'You cannot review your own request';
    end if;
    if v_actor.role <> 'hr_admin' and not (p_actor_id = any(v_request.approver_ids)) then
        raise exception using errcode = 'PT403', message = 'You are not an assigned approver for this request';
    end if;
    if v_request.status <> 'pending' then
        if v_request.status = p_status and v_request.reviewed_by = p_actor_id
            and coalesce(v_request.reviewer_comment, '') = v_comment then
            return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
        end if;
        raise exception using errcode = 'PT409', message = 'Request is no longer pending';
    end if;

    update public.hr_requests set status = p_status, reviewer_comment = p_reviewer_comment,
        reviewed_by = p_actor_id, reviewed_at = now()
    where id = p_request_id returning * into v_request;
    insert into public.request_events (request_id, actor_id, event_type, from_status, to_status, comment, created_at)
    values (p_request_id, p_actor_id, p_status::text, 'pending', p_status, v_comment, v_request.reviewed_at);
    insert into public.notifications (employee_id, request_id, notification_type, title, body)
    values (v_request.employee_id, p_request_id, 'request_status_changed', 'Статус заявки изменён',
        case when p_status = 'rejected' then 'Заявка отклонена. Причина: ' || v_comment else 'Ваша заявка согласована.' end);
    return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
end;
$$;

create function public.cancel_hr_request(p_actor_id uuid, p_request_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    v_request public.hr_requests%rowtype;
begin
    -- Review and cancellation use the same row lock: exactly one pending-to-
    -- terminal transition wins. Repeated owner cancellation is idempotent.
    select * into v_request from public.hr_requests where id = p_request_id for update;
    if not found then raise exception using errcode = 'PT404', message = 'Request not found'; end if;
    if p_actor_id is null or v_request.employee_id <> p_actor_id then
        raise exception using errcode = 'PT403', message = 'Only the owner can cancel a request';
    end if;
    if v_request.status = 'cancelled' then
        return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
    end if;
    if v_request.status <> 'pending' then
        raise exception using errcode = 'PT409', message = 'Only pending requests can be cancelled';
    end if;
    update public.hr_requests set status = 'cancelled', cancelled_at = now()
    where id = p_request_id returning * into v_request;
    insert into public.request_events (request_id, actor_id, event_type, from_status, to_status, comment, created_at)
    values (p_request_id, p_actor_id, 'cancelled', 'pending', 'cancelled', 'Отозвана автором', v_request.cancelled_at);
    insert into public.notifications (employee_id, request_id, notification_type, title, body)
    select id, p_request_id, 'request_cancelled', 'Заявка отозвана',
        case when id = p_actor_id then 'Вы отозвали заявку. Она больше не ожидает согласования.'
             else 'Автор отозвал заявку. Согласование больше не требуется.' end
    from public.employee_profiles where id = p_actor_id or id = any(v_request.approver_ids);
    return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
end;
$$;

revoke execute on function public.get_hr_request_routing(uuid) from public, anon, authenticated;
grant execute on function public.get_hr_request_routing(uuid) to service_role;
revoke execute on function public.cancel_hr_request(uuid, uuid) from public, anon, authenticated;
grant execute on function public.cancel_hr_request(uuid, uuid) to service_role;
revoke execute on function public.create_hr_request(uuid, public.hr_request_type, date, date, numeric, text, uuid) from public, anon, authenticated;
grant execute on function public.create_hr_request(uuid, public.hr_request_type, date, date, numeric, text, uuid) to service_role;
revoke execute on function public.review_hr_request(uuid, uuid, public.hr_request_status, text) from public, anon, authenticated;
grant execute on function public.review_hr_request(uuid, uuid, public.hr_request_status, text) to service_role;
notify pgrst, 'reload schema';
commit;
