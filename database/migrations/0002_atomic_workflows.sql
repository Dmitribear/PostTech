-- Apply after 0001, before starting the updated API. Safe to run again.
-- Notifications and request history commit (or roll back) with the originating write.
begin;

lock table public.hr_requests, public.course_assignments in share row exclusive mode;

create table if not exists public.hr_request_events (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null references public.hr_requests(id) on delete cascade,
    event_type text not null check (event_type in ('created', 'status_changed', 'snapshot')),
    old_status public.hr_request_status,
    new_status public.hr_request_status not null,
    actor_id uuid references public.employee_profiles(id) on delete set null,
    comment text,
    created_at timestamptz not null default now()
);

create index if not exists hr_request_events_request_created_idx
    on public.hr_request_events(request_id, created_at, id);
alter table public.hr_request_events enable row level security;
grant select, insert on public.hr_request_events to service_role;

-- We cannot recover historical changes that were never recorded. Mark existing
-- records as snapshots instead of presenting inferred events as an audit trail.
insert into public.hr_request_events
    (request_id, event_type, new_status, actor_id, comment, created_at)
select r.id, 'snapshot', r.status, coalesce(r.reviewed_by, r.employee_id),
       r.reviewer_comment, coalesce(r.reviewed_at, r.created_at)
from public.hr_requests r
where not exists (select 1 from public.hr_request_events e where e.request_id = r.id);

create or replace function public.record_hr_request_events()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
    employee public.employee_profiles%rowtype;
begin
    if tg_op = 'INSERT' then
        insert into public.hr_request_events
            (request_id, event_type, new_status, actor_id, comment, created_at)
        values (new.id, 'created', new.status, new.employee_id, new.comment, new.created_at);

        if new.status = 'pending' then
            select * into strict employee from public.employee_profiles where id = new.employee_id;
            if employee.manager_id is not null then
                insert into public.notifications
                    (employee_id, request_id, notification_type, title, body)
                values (employee.manager_id, new.id, 'request_created', 'Новая заявка сотрудника',
                        employee.full_name || ' создал(а) заявку: ' || new.request_type::text || '.');
            else
                insert into public.notifications
                    (employee_id, request_id, notification_type, title, body)
                select id, new.id, 'request_created', 'Новая заявка сотрудника',
                       employee.full_name || ' создал(а) заявку: ' || new.request_type::text || '.'
                from public.employee_profiles where role = 'hr_admin';
            end if;
        end if;
    elsif old.status is distinct from new.status then
        insert into public.hr_request_events
            (request_id, event_type, old_status, new_status, actor_id, comment)
        values (new.id, 'status_changed', old.status, new.status, new.reviewed_by, new.reviewer_comment);
        insert into public.notifications
            (employee_id, request_id, notification_type, title, body)
        values (new.employee_id, new.id, 'request_status_changed', 'Статус заявки изменён',
                'Ваша заявка получила статус: ' || new.status::text || '.');
    end if;
    return new;
end;
$$;

drop trigger if exists hr_requests_record_events on public.hr_requests;
create trigger hr_requests_record_events
after insert or update on public.hr_requests
for each row execute function public.record_hr_request_events();

create or replace function public.record_course_notifications()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
    employee public.employee_profiles%rowtype;
    course_title text;
    just_completed boolean;
begin
    if tg_op = 'INSERT' then
        insert into public.notifications (employee_id, notification_type, title, body)
        values (new.employee_id, 'course_assigned', 'Назначено обучение',
                'Вам назначен новый учебный курс Jana Academy.');
        just_completed := new.status = 'completed';
    else
        just_completed := new.status = 'completed' and old.status <> 'completed';
    end if;

    if just_completed then
        select * into strict employee from public.employee_profiles where id = new.employee_id;
        select title into strict course_title from public.courses where id = new.course_id;
        insert into public.notifications (employee_id, notification_type, title, body)
        values (new.employee_id, 'course_completed', 'Обучение завершено',
                'Вы завершили курс «' || course_title || '» с результатом ' ||
                coalesce(new.score_percent::text, '0') || '%.');
        if employee.manager_id is not null and employee.manager_id <> new.employee_id then
            insert into public.notifications (employee_id, notification_type, title, body)
            values (employee.manager_id, 'course_completed', 'Обучение завершено',
                    employee.full_name || ' завершил(а) курс «' || course_title ||
                    '» с результатом ' || coalesce(new.score_percent::text, '0') || '%.');
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists course_assignments_notify on public.course_assignments;
create trigger course_assignments_notify
after insert or update on public.course_assignments
for each row execute function public.record_course_notifications();

-- These trigger functions are internal; they are not callable RPC endpoints.
revoke all on function public.record_hr_request_events() from public;
revoke all on function public.record_course_notifications() from public;

commit;
