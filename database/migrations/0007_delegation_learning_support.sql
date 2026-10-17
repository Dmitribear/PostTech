-- Stages 7–10. All commands are server-only; actor comes from verified Auth.
begin;
create table public.approval_delegations (
 id uuid primary key, manager_id uuid not null references public.employee_profiles(id),
 deputy_id uuid not null references public.employee_profiles(id),
 starts_on date not null, ends_on date not null, reason text not null default '',
 created_by uuid not null references public.employee_profiles(id), created_at timestamptz not null default now(),
 revoked_at timestamptz, revoked_by uuid references public.employee_profiles(id), check(manager_id<>deputy_id), check(ends_on>=starts_on),
 check(ends_on-starts_on<=365), check(length(reason)<=1000)
);
alter table public.approval_delegations enable row level security;
revoke all on public.approval_delegations from anon, authenticated;
grant all on public.approval_delegations to service_role;

create function public.active_delegation_principals(p_actor_id uuid) returns setof uuid
language sql stable security invoker set search_path=public,pg_temp as $$
 select d.manager_id from approval_delegations d
 join employee_profiles e on e.id=d.deputy_id and e.role in ('manager','hr_admin')
 join employee_profiles primary_manager on primary_manager.id=d.manager_id and primary_manager.role in ('manager','hr_admin')
 where d.deputy_id=p_actor_id and d.revoked_at is null
 and (now() at time zone 'Asia/Almaty')::date between d.starts_on and d.ends_on
 and not exists(select 1 from hr_requests r where r.employee_id=p_actor_id and r.request_type='leave'
   and r.status='approved' and (now() at time zone 'Asia/Almaty')::date between r.start_date and r.end_date)
$$;

create function public.manage_approval_delegation(p_actor_id uuid,p_id uuid,p_manager_id uuid,p_deputy_id uuid,
 p_starts_on date,p_ends_on date,p_reason text,p_revoke boolean default false) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare d approval_delegations; today date := (now() at time zone 'Asia/Almaty')::date;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then
  raise exception using errcode='PT403',message='HR role required'; end if;
 perform pg_advisory_xact_lock(71007);
 select * into d from approval_delegations where id=p_id for update;
 if p_revoke then
  if d.id is null then raise exception using errcode='PT404',message='Delegation not found'; end if;
  update approval_delegations set revoked_at=coalesce(revoked_at,now()),revoked_by=coalesce(revoked_by,p_actor_id) where id=p_id returning * into d;
  return to_jsonb(d);
 end if;
 if d.id is not null then
  if (d.manager_id,d.deputy_id,d.starts_on,d.ends_on,d.reason) is distinct from
     (p_manager_id,p_deputy_id,p_starts_on,p_ends_on,p_reason) then
   raise exception using errcode='PT409',message='Operation key already used'; end if;
  return to_jsonb(d);
 end if;
 if p_manager_id is null or p_deputy_id is null or p_manager_id=p_deputy_id or p_starts_on is null
   or p_ends_on is null or p_starts_on<today or p_ends_on<p_starts_on or p_ends_on-p_starts_on>365
   or length(coalesce(p_reason,''))>1000 then
  raise exception using errcode='PT422',message='Invalid delegation dates or participants'; end if;
 if (select count(*) from employee_profiles where id in (p_manager_id,p_deputy_id) and role in ('manager','hr_admin'))<>2 then
  raise exception using errcode='PT422',message='Both participants must be managers or HR'; end if;
 -- No overlapping replacements, chains or cycles; delegation is never transitive.
 if exists(select 1 from approval_delegations where revoked_at is null
   and starts_on<=p_ends_on and ends_on>=p_starts_on
   and (manager_id=p_manager_id or deputy_id=p_manager_id or manager_id=p_deputy_id)) then
  raise exception using errcode='PT409',message='Overlapping delegation or delegation chain'; end if;
 if exists(select 1 from hr_requests where employee_id=p_deputy_id and request_type='leave' and status='approved'
   and start_date<=p_ends_on and end_date>=p_starts_on) then
  raise exception using errcode='PT409',message='Deputy is on approved leave'; end if;
 insert into approval_delegations(id,manager_id,deputy_id,starts_on,ends_on,reason,created_by)
 values(p_id,p_manager_id,p_deputy_id,p_starts_on,p_ends_on,coalesce(p_reason,''),p_actor_id) returning * into d;
 insert into notifications(employee_id,notification_type,title,body) values
 (p_deputy_id,'delegation_assigned','Вам назначено замещение',p_starts_on::text||' — '||p_ends_on::text);
 return to_jsonb(d);
end $$;

-- Immutable audit alongside decisions, without broadening access to employee profiles.
alter table public.request_events add column delegation_id uuid references public.approval_delegations(id);

alter table public.courses add column publication_state text not null default 'published'
 check(publication_state in ('draft','published','archived'));
alter table public.courses add column family_id uuid;
alter table public.courses add column version integer not null default 1;
alter table public.courses add column revision integer not null default 1;
alter table public.courses add column translations jsonb not null default '{}';
update public.courses set family_id=id,publication_state=case when active then 'published' else 'archived' end;
alter table public.courses alter column family_id set not null;
grant insert,update on public.courses to service_role;
create unique index courses_family_version on public.courses(family_id,version);
alter table public.course_assignments add column due_on date;
create table public.course_deadline_events (
 id uuid primary key default gen_random_uuid(), assignment_id uuid not null references public.course_assignments(id),
 actor_id uuid not null references public.employee_profiles(id), old_due_on date,new_due_on date,created_at timestamptz not null default now()
);
alter table public.course_deadline_events enable row level security;
revoke all on public.course_deadline_events from anon,authenticated;
grant all on public.course_deadline_events to service_role;

create function public.edit_academy_course(p_actor_id uuid,p_id uuid,p_action text,p_revision integer,p_data jsonb)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare c courses; family uuid; next_version integer;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then
  raise exception using errcode='PT403',message='HR role required'; end if;
 perform pg_advisory_xact_lock(81008);
 select * into c from courses where id=p_id for update;
 if p_action='create' then
  if c.id is not null then return to_jsonb(c); end if;
  family:=coalesce((p_data->>'family_id')::uuid,p_id);
  if family<>p_id and not exists(select 1 from courses where family_id=family) then
   raise exception using errcode='PT404',message='Course family not found'; end if;
  select coalesce(max(version),0)+1 into next_version from courses where family_id=family;
  insert into courses(id,title,description,duration_minutes,material_markdown,quiz,active,category,audience,passing_score,publication_state,family_id,version,translations)
  values(p_id,p_data->>'title',p_data->>'description',(p_data->>'duration_minutes')::int,p_data->>'material_markdown',p_data->'quiz',false,
   p_data->>'category',p_data->>'audience',(p_data->>'passing_score')::int,'draft',family,next_version,coalesce(p_data->'translations','{}')) returning * into c;
 else
  if c.id is null then raise exception using errcode='PT404',message='Course not found'; end if;
  if c.revision<>p_revision then raise exception using errcode='PT409',message='Course changed; reload before saving'; end if;
  if p_action in ('save','publish') and c.publication_state<>'draft' then
   raise exception using errcode='PT409',message='Published courses are immutable; create a new version'; end if;
  if p_action='save' then
   update courses set title=p_data->>'title',description=p_data->>'description',duration_minutes=(p_data->>'duration_minutes')::int,
    material_markdown=p_data->>'material_markdown',quiz=p_data->'quiz',category=p_data->>'category',audience=p_data->>'audience',
    passing_score=(p_data->>'passing_score')::int,translations=coalesce(p_data->'translations','{}'),revision=revision+1
   where id=p_id returning * into c;
  elsif p_action='publish' then
   if btrim(c.title)='' or btrim(c.material_markdown)='' or jsonb_array_length(c.quiz)=0 then
    raise exception using errcode='PT422',message='Course needs title, material and quiz'; end if;
   update courses set active=false,publication_state='archived',revision=revision+1
    where family_id=c.family_id and publication_state='published';
   update courses set active=true,publication_state='published',revision=revision+1 where id=p_id returning * into c;
  elsif p_action='archive' then
   update courses set active=false,publication_state='archived',revision=revision+1 where id=p_id returning * into c;
  else raise exception using errcode='PT422',message='Unknown course action'; end if;
 end if;
 return to_jsonb(c);
end $$;

create function public.set_course_deadline(p_actor_id uuid,p_assignment_id uuid,p_due_on date) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare a course_assignments; old_date date;
begin
 select * into a from course_assignments where id=p_assignment_id for update;
 if a.id is null then raise exception using errcode='PT404',message='Assignment not found'; end if;
 if not exists(select 1 from employee_profiles actor join employee_profiles employee on employee.id=a.employee_id
  where actor.id=p_actor_id and (actor.role='hr_admin' or (actor.role='manager' and employee.manager_id=actor.id))) then
  raise exception using errcode='PT403',message='You cannot manage this employee'; end if;
 if a.due_on is not distinct from p_due_on then return to_jsonb(a); end if;
 if a.status='completed' then raise exception using errcode='PT409',message='Completed learning is immutable'; end if;
 if p_due_on<(now() at time zone 'Asia/Almaty')::date then raise exception using errcode='PT422',message='Deadline cannot be in the past'; end if;
 old_date:=a.due_on;
 update course_assignments set due_on=p_due_on where id=a.id returning * into a;
 insert into course_deadline_events(assignment_id,actor_id,old_due_on,new_due_on) values(a.id,p_actor_id,old_date,p_due_on);
 insert into notifications(employee_id,course_id,notification_type,title,body)
 values(a.employee_id,a.course_id,'course_deadline','Срок обучения изменён',coalesce(p_due_on::text,'Без срока'));
 return to_jsonb(a);
end $$;

create function public.assign_academy_course_due(p_actor_id uuid,p_employee_id uuid,p_course_id uuid,p_due_on date) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare a jsonb;
begin
 a:=assign_academy_course(p_actor_id,p_employee_id,p_course_id);
 if p_due_on is not null then a:=set_course_deadline(p_actor_id,(a->>'id')::uuid,p_due_on); end if;
 return a;
end $$;

create table public.hr_tickets (
 id uuid primary key, employee_id uuid not null references public.employee_profiles(id),
 question text not null check(length(btrim(question)) between 3 and 2000),
 context text not null default '' check(length(context)<=6000), consented_at timestamptz not null default now(),
 status text not null default 'open' check(status in ('open','resolved')),
 answer text, answered_by uuid references public.employee_profiles(id), answered_at timestamptz,
 created_at timestamptz not null default now(),
 check((status='open' and answer is null and answered_by is null and answered_at is null) or
 (status='resolved' and length(btrim(answer)) between 3 and 6000 and answered_by is not null and answered_at is not null)),
 check(answered_by is distinct from employee_id)
);
alter table public.hr_tickets enable row level security;
revoke all on public.hr_tickets from anon,authenticated;
grant all on public.hr_tickets to service_role;
alter table public.notifications add column ticket_id uuid references public.hr_tickets(id);
create function public.create_hr_ticket(p_actor_id uuid,p_id uuid,p_question text,p_context text,p_consent boolean)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare t hr_tickets;
begin
 if p_consent is distinct from true then raise exception using errcode='PT422',message='Confirm sharing with HR'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_id::text,10));
 select * into t from hr_tickets where id=p_id;
 if t.id is not null then
  if (t.employee_id,t.question,t.context) is distinct from (p_actor_id,p_question,p_context) then
   raise exception using errcode='PT409',message='Operation key already used'; end if;
  return to_jsonb(t);
 end if;
 if not exists(select 1 from employee_profiles where role='hr_admin' and id<>p_actor_id) then
  raise exception using errcode='PT409',message='No HR recipient available'; end if;
 insert into hr_tickets(id,employee_id,question,context) values(p_id,p_actor_id,p_question,p_context) returning * into t;
 insert into notifications(employee_id,ticket_id,notification_type,title,body)
 select id,t.id,'hr_ticket_created','Новое обращение в HR','Откройте обращение, чтобы ответить.' from employee_profiles where role='hr_admin' and id<>p_actor_id;
 return to_jsonb(t);
end $$;
create function public.answer_hr_ticket(p_actor_id uuid,p_id uuid,p_answer text) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare t hr_tickets;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then
  raise exception using errcode='PT403',message='HR role required'; end if;
 select * into t from hr_tickets where id=p_id for update;
 if t.id is null then raise exception using errcode='PT404',message='Ticket not found'; end if;
 if t.employee_id=p_actor_id then raise exception using errcode='PT403',message='Another HR must answer your question'; end if;
 if t.status='resolved' then
  if t.answered_by=p_actor_id and t.answer=p_answer then return to_jsonb(t); end if;
  raise exception using errcode='PT409',message='Ticket already answered'; end if;
 if length(btrim(p_answer)) not between 3 and 6000 or p_answer is null then
  raise exception using errcode='PT422',message='Answer must contain 3 to 6000 characters'; end if;
 update hr_tickets set status='resolved',answer=p_answer,answered_by=p_actor_id,answered_at=now() where id=p_id returning * into t;
 insert into notifications(employee_id,ticket_id,notification_type,title,body)
 values(t.employee_id,t.id,'hr_ticket_answered','HR ответил на обращение','Откройте обращение, чтобы прочитать ответ.');
 return to_jsonb(t);
end $$;

-- Explicit grants: no client can impersonate an actor through an RPC.
do $$ declare f record; begin
 for f in select oid::regprocedure signature from pg_proc where pronamespace='public'::regnamespace and proname in
 ('active_delegation_principals','manage_approval_delegation','edit_academy_course','set_course_deadline',
 'assign_academy_course_due','create_hr_ticket','answer_hr_ticket') loop
  execute format('revoke all on function %s from public,anon,authenticated',f.signature);
  execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
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
    perform pg_advisory_xact_lock_shared(71007);
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
    if v_actor.role <> 'hr_admin' and not (p_actor_id = any(v_request.approver_ids))
        and not (v_request.status='pending' and exists(select 1 from public.active_delegation_principals(p_actor_id) principal where principal=any(v_request.approver_ids)))
        and v_request.reviewed_by is distinct from p_actor_id then
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
    insert into public.request_events (request_id, actor_id, event_type, from_status, to_status, comment, created_at, delegation_id)
    values (p_request_id, p_actor_id, p_status::text, 'pending', p_status, v_comment, v_request.reviewed_at, (select d.id from public.approval_delegations d where d.deputy_id=p_actor_id and d.manager_id=any(v_request.approver_ids) and d.revoked_at is null and (now() at time zone 'Asia/Almaty')::date between d.starts_on and d.ends_on order by d.created_at desc limit 1));
    insert into public.notifications (employee_id, request_id, notification_type, title, body)
    values (v_request.employee_id, p_request_id, 'request_status_changed', 'Статус заявки изменён',
        case when p_status = 'rejected' then 'Заявка отклонена. Причина: ' || v_comment else 'Ваша заявка согласована.' end);
    return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
end;
$$;
create or replace function public.update_academy_progress(p_actor_id uuid, p_course_id uuid, p_progress_percent integer)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_assignment public.course_assignments%rowtype;
    v_course public.courses%rowtype;
begin
    if p_progress_percent is null or p_progress_percent not between 0 and 99 then
        raise exception using errcode = 'PT422', message = 'Progress must be between 0 and 99';
    end if;
    select * into v_assignment from public.course_assignments
    where course_id = p_course_id and employee_id = p_actor_id for update;
    if not found then raise exception using errcode = 'PT404', message = 'Course assignment not found'; end if;
    -- A late PATCH can never reopen a course or erase its completed result.
    if v_assignment.status = 'completed' then return to_jsonb(v_assignment); end if;
    select * into v_course from public.courses where id = p_course_id for share;
    if not found then raise exception using errcode = 'PT404', message = 'Course not found'; end if;
    if p_progress_percent >= 90 and btrim(v_course.material_markdown) = '' then
        raise exception using errcode = 'PT409', message = 'Course material is not configured';
    end if;
    update public.course_assignments set
        progress_percent = greatest(progress_percent, p_progress_percent),
        status = case when greatest(progress_percent, p_progress_percent) > 0
                      then 'in_progress'::public.course_status else 'not_started'::public.course_status end,
        material_completed_at = case when p_progress_percent >= 90 then coalesce(material_completed_at, now()) else material_completed_at end
    where id = v_assignment.id returning * into v_assignment;
    return to_jsonb(v_assignment);
end;
$$;
create or replace function public.submit_academy_quiz(p_actor_id uuid, p_course_id uuid, p_answers jsonb, p_submission_id uuid)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_assignment public.course_assignments%rowtype;
    v_course public.courses%rowtype;
    v_employee public.employee_profiles%rowtype;
    v_previous public.course_attempts%rowtype;
    v_manager public.employee_profiles%rowtype;
    v_question jsonb;
    v_question_id text;
    v_answer integer;
    v_correct integer := 0;
    v_total integer;
    v_score numeric(5,2);
    v_passed boolean;
begin
    select * into v_assignment from public.course_assignments
    where course_id = p_course_id and employee_id = p_actor_id for update;
    if not found then raise exception using errcode = 'PT404', message = 'Course assignment not found'; end if;
    -- The assignment lock serializes submissions and progress updates. A
    -- completed result is immutable even if a browser sends stale answers.
    if v_assignment.status = 'completed' then return to_jsonb(v_assignment); end if;
    if p_submission_id is null then raise exception using errcode = 'PT422', message = 'Submission identifier is required'; end if;
    select * into v_previous from public.course_attempts
    where assignment_id = v_assignment.id and submission_id = p_submission_id;
    if found then
        if v_previous.answers is distinct from p_answers then
            raise exception using errcode = 'PT409', message = 'Quiz submission key was already used for different answers';
        end if;
        return to_jsonb(v_assignment);
    end if;
    if v_assignment.material_completed_at is null then
        raise exception using errcode = 'PT409', message = 'Read the course material before submitting the quiz';
    end if;
    select * into v_course from public.courses where id = p_course_id for share;
    if not found then raise exception using errcode = 'PT404', message = 'Course not found'; end if;
    if jsonb_typeof(v_course.quiz) is distinct from 'array' or jsonb_array_length(v_course.quiz) = 0 then
        raise exception using errcode = 'PT409', message = 'This course has no configured quiz';
    end if;
    v_total := jsonb_array_length(v_course.quiz);
    if v_total > 100 then raise exception using errcode = 'PT409', message = 'Course quiz configuration is invalid'; end if;
    if jsonb_typeof(p_answers) is distinct from 'object' then
        raise exception using errcode = 'PT422', message = 'Quiz answers must be an object';
    end if;
    if (select count(*) from jsonb_object_keys(p_answers)) <> v_total then
        raise exception using errcode = 'PT422', message = 'Answer every quiz question exactly once';
    end if;
    if (select count(distinct question->>'id') from jsonb_array_elements(v_course.quiz) question) <> v_total then
        raise exception using errcode = 'PT409', message = 'Course quiz configuration is invalid';
    end if;
    for v_question in select value from jsonb_array_elements(v_course.quiz) loop
        v_question_id := v_question->>'id';
        if v_question_id is null or v_question_id = '' or
           jsonb_typeof(v_question->'options') is distinct from 'array' or
           coalesce(v_question->>'answer_index', '') !~ '^[0-9]{1,6}$' then
            raise exception using errcode = 'PT409', message = 'Course quiz configuration is invalid';
        end if;
        if jsonb_array_length(v_question->'options') < 2 or
           (v_question->>'answer_index')::integer >= jsonb_array_length(v_question->'options') then
            raise exception using errcode = 'PT409', message = 'Course quiz configuration is invalid';
        end if;
        if not (p_answers ? v_question_id) or jsonb_typeof(p_answers->v_question_id) is distinct from 'number' or
           coalesce(p_answers->>v_question_id, '') !~ '^[0-9]{1,6}$' then
            raise exception using errcode = 'PT422', message = 'Quiz answer option is invalid';
        end if;
        v_answer := (p_answers->>v_question_id)::integer;
        if v_answer >= jsonb_array_length(v_question->'options') then
            raise exception using errcode = 'PT422', message = 'Quiz answer option is invalid';
        end if;
        if v_answer = (v_question->>'answer_index')::integer then v_correct := v_correct + 1; end if;
    end loop;
    v_score := round(v_correct * 100.0 / v_total, 2);
    v_passed := v_score >= v_course.passing_score;
    insert into public.course_attempts(assignment_id, submission_id, attempt_number, answers, score_percent, passed)
    values (v_assignment.id, p_submission_id, v_assignment.attempt_count + 1, p_answers, v_score, v_passed);
    update public.course_assignments set
        status = case when v_passed then 'completed'::public.course_status else 'in_progress'::public.course_status end,
        progress_percent = case when v_passed then 100 else greatest(progress_percent, 90) end,
        score_percent = v_score, attempt_count = attempt_count + 1, last_attempt_at = now(),
        completed_at = case when v_passed then now() else null end
    where id = v_assignment.id returning * into v_assignment;
    if v_passed then
        select * into v_employee from public.employee_profiles where id = p_actor_id for share;
        insert into public.notifications(employee_id, course_id, notification_type, title, body)
        values (p_actor_id, p_course_id, 'course_completed', 'Обучение завершено',
                format('Вы завершили курс «%s». Результат: %s%%.', v_course.title, v_score));
        if v_employee.manager_id is not null and v_employee.manager_id <> p_actor_id then
            select * into v_manager from public.employee_profiles
            where id = v_employee.manager_id and role in ('manager', 'hr_admin') for share;
            if found then
                insert into public.notifications(employee_id, course_id, notification_type, title, body)
                values (v_manager.id, p_course_id, 'team_course_completed', 'Сотрудник завершил обучение',
                        format('%s завершил(а) курс «%s». Результат: %s%%.', v_employee.full_name, v_course.title, v_score));
            end if;
        end if;
    end if;
    return to_jsonb(v_assignment);
end;
$$;
notify pgrst,'reload schema';
commit;
