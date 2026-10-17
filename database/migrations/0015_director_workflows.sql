begin;

-- Apply after 0014, in a separate transaction from the enum change.


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
security definer
set search_path = ''
as $$
declare
    actor_role public.app_role;
    existing_role public.app_role;
begin
    -- Shared by every role mutation. Recheck the actor AFTER taking the lock:
    -- otherwise two administrators could demote each other using stale rights.
    perform pg_catalog.pg_advisory_xact_lock(71007);
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
    if p_role not in ('manager', 'director', 'hr_admin') and exists (
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
    if v_actor.role not in ('manager', 'director', 'hr_admin') then
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

create or replace function public.get_hr_request_routing(p_actor_id uuid)
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
    where id = v_actor.manager_id and id <> p_actor_id and role in ('manager', 'director', 'hr_admin');
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

create or replace function public.assign_academy_course(p_actor_id uuid, p_employee_id uuid, p_course_id uuid)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_actor public.employee_profiles%rowtype;
    v_employee public.employee_profiles%rowtype;
    v_course public.courses%rowtype;
    v_assignment public.course_assignments%rowtype;
begin
    select * into v_actor from public.employee_profiles where id = p_actor_id for share;
    if not found or v_actor.role not in ('manager', 'director', 'hr_admin') then
        raise exception using errcode = 'PT403', message = 'Manager or HR role required';
    end if;
    select * into v_employee from public.employee_profiles where id = p_employee_id for share;
    if not found then raise exception using errcode = 'PT404', message = 'Employee not found'; end if;
    if v_actor.role <> 'hr_admin' and v_employee.manager_id is distinct from p_actor_id then
        raise exception using errcode = 'PT403', message = 'You cannot manage this employee';
    end if;
    select * into v_course from public.courses where id = p_course_id and active for share;
    if not found then raise exception using errcode = 'PT404', message = 'Course not found'; end if;
    insert into public.course_assignments(course_id, employee_id, assigned_by)
    values (p_course_id, p_employee_id, p_actor_id)
    on conflict (course_id, employee_id) do nothing returning * into v_assignment;
    if not found then raise exception using errcode = 'PT409', message = 'Course is already assigned'; end if;
    insert into public.notifications(employee_id, course_id, notification_type, title, body)
    values (p_employee_id, p_course_id, 'course_assigned', 'Назначено обучение',
            format('Вам назначен курс «%s». Изучите материал и пройдите тест в Jana Academy.', v_course.title));
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
            where id = v_employee.manager_id and role in ('manager', 'director', 'hr_admin') for share;
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

create or replace function public.issue_registration_invitation(p_actor_id uuid, p_token_hash text, p_details jsonb)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_invite public.registration_invitations;
    v_email text := lower(btrim(p_details->>'email'));
    v_manager uuid := (p_details->>'manager_id')::uuid;
    v_hours integer := coalesce((p_details->>'expires_in_hours')::integer,72);
begin
    if not exists (select 1 from public.employee_profiles where id = p_actor_id and role = 'hr_admin') then
        raise exception using errcode='PT403', message='HR administrator role required';
    end if;
    if v_hours < 1 or v_hours > 168 then
        raise exception using errcode='PT422', message='Invitation lifetime must be between 1 and 168 hours';
    end if;
    if v_manager is not null then
        perform id from public.employee_profiles where id=v_manager and role in ('manager', 'director', 'hr_admin') for share;
        if not found then raise exception using errcode='PT422', message='Invitation manager must be a manager or HR administrator'; end if;
    end if;
    perform pg_advisory_xact_lock(hashtextextended(v_email,71224));
    if exists(select 1 from public.employee_profiles where lower(email)=v_email or employee_code=p_details->>'employee_code') then
        raise exception using errcode='PT409', message='An employee profile already exists for this email or employee code';
    end if;
    update public.registration_invitations set revoked_at=now()
    where consumed_at is null and revoked_at is null and expires_at <= now()
      and (email=v_email or employee_code=p_details->>'employee_code');
    if exists(select 1 from public.registration_invitations where consumed_at is null and revoked_at is null
        and (email=v_email or employee_code=p_details->>'employee_code')) then
        raise exception using errcode='PT409', message='An active invitation already exists for this employee';
    end if;
    insert into public.registration_invitations(token_hash,email,employee_code,company,job_title,department,
        hired_at,manager_id,role,vacation_days_remaining,created_by,expires_at)
    values(p_token_hash,v_email,p_details->>'employee_code',p_details->>'company',p_details->>'job_title',
        p_details->>'department',(p_details->>'hired_at')::date,v_manager,
        coalesce((p_details->>'role')::public.app_role,'worker'),
        coalesce((p_details->>'vacation_days_remaining')::numeric,0),p_actor_id,now()+make_interval(hours=>v_hours))
    returning * into v_invite;
    return jsonb_build_object('id',v_invite.id,'email',v_invite.email,'role',v_invite.role,
        'department',v_invite.department,'expires_at',v_invite.expires_at);
exception when unique_violation then
    raise exception using errcode='PT409', message='An active invitation already exists for this employee';
end;
$$;

create or replace function public.complete_registration_invitation(p_token_hash text, p_auth_user_id uuid,
    p_first_name text default null,p_last_name text default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_invite public.registration_invitations;
    v_email text;
    v_confirmed timestamptz;
    v_profile public.employee_profiles;
begin
    select * into v_invite from public.registration_invitations where token_hash=p_token_hash for update;
    if not found then raise exception using errcode='PT404', message='Invitation code is invalid'; end if;
    -- Never trust the sign-up response, user metadata, or browser claims. Check
    -- authoritative Auth state again within the profile-creation transaction.
    select lower(email),email_confirmed_at into v_email,v_confirmed from auth.users where id=p_auth_user_id for share;
    if v_confirmed is null or v_email is distinct from v_invite.email then
        raise exception using errcode='PT403', message='Confirm the invited email before activating your workspace';
    end if;
    if v_invite.consumed_at is not null then
        if v_invite.consumed_by is distinct from p_auth_user_id then
            raise exception using errcode='PT409', message='Invitation has already been used';
        end if;
        return jsonb_build_object('profile_id',v_invite.profile_id,'role',v_invite.role);
    end if;
    perform public.check_registration_invitation(p_token_hash,false);
    if v_invite.first_name is null or v_invite.last_name is null then
        if p_first_name is null or p_last_name is null or length(btrim(p_first_name)) not between 1 and 80
            or length(btrim(p_last_name)) not between 1 and 80 then
            raise exception using errcode='PT422', message='Enter your first and last name to activate your workspace';
        end if;
        v_invite.first_name := btrim(p_first_name);
        v_invite.last_name := btrim(p_last_name);
    end if;
    if v_invite.manager_id is not null then
        perform id from public.employee_profiles where id=v_invite.manager_id
            and auth_user_id<>p_auth_user_id and role in ('manager', 'director', 'hr_admin') for share;
        if not found then raise exception using errcode='PT409', message='Your reporting manager has changed. Contact HR'; end if;
    end if;
    -- A second invitation cannot alter an existing account's role or balance.
    if exists(select 1 from public.employee_profiles where auth_user_id=p_auth_user_id
        or lower(email)=v_email or employee_code=v_invite.employee_code) then
        raise exception using errcode='PT409', message='An employee profile already exists. Contact HR';
    end if;
    insert into public.employee_profiles(auth_user_id,employee_code,full_name,email,company,job_title,department,
        manager_id,hired_at,vacation_days_remaining,role,external_source)
    values(p_auth_user_id,v_invite.employee_code,v_invite.first_name||' '||v_invite.last_name,v_invite.email,
        v_invite.company,v_invite.job_title,v_invite.department,v_invite.manager_id,v_invite.hired_at,
        v_invite.vacation_days_remaining,v_invite.role,'hr-invitation') returning * into v_profile;
    update public.registration_invitations set consumed_at=now(),consumed_by=p_auth_user_id,profile_id=v_profile.id,
        first_name=v_invite.first_name,last_name=v_invite.last_name
        where id=v_invite.id;
    return jsonb_build_object('profile_id',v_profile.id,'role',v_profile.role);
exception when unique_violation then
    raise exception using errcode='PT409', message='An employee profile already exists. Contact HR';
end;
$$;

create or replace function public.active_delegation_principals(p_actor_id uuid) returns setof uuid
language sql stable security invoker set search_path=public,pg_temp as $$
 select d.manager_id from approval_delegations d
 join employee_profiles e on e.id=d.deputy_id and e.role in ('manager', 'director', 'hr_admin')
 join employee_profiles primary_manager on primary_manager.id=d.manager_id and primary_manager.role in ('manager', 'director', 'hr_admin')
 where d.deputy_id=p_actor_id and d.revoked_at is null
 and (now() at time zone 'Asia/Almaty')::date between d.starts_on and d.ends_on
 and not exists(select 1 from hr_requests r where r.employee_id=p_actor_id and r.request_type='leave'
   and r.status='approved' and (now() at time zone 'Asia/Almaty')::date between r.start_date and r.end_date)
$$;

create or replace function public.manage_approval_delegation(p_actor_id uuid,p_id uuid,p_manager_id uuid,p_deputy_id uuid,
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
 if (select count(*) from employee_profiles where id in (p_manager_id,p_deputy_id) and role in ('manager', 'director', 'hr_admin'))<>2 then
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

create or replace function public.set_course_deadline(p_actor_id uuid,p_assignment_id uuid,p_due_on date) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare a course_assignments; old_date date;
begin
 select * into a from course_assignments where id=p_assignment_id for update;
 if a.id is null then raise exception using errcode='PT404',message='Assignment not found'; end if;
 if not exists(select 1 from employee_profiles actor join employee_profiles employee on employee.id=a.employee_id
  where actor.id=p_actor_id and (actor.role='hr_admin' or (actor.role in ('manager','director') and employee.manager_id=actor.id))) then
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

create or replace function public.create_learning_track(p_actor_id uuid,p_id uuid,p_title text,p_steps jsonb,p_auto_role text default null) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare s jsonb; n integer:=0; old learning_tracks;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 perform pg_advisory_xact_lock(81101);
 select * into old from learning_tracks where id=p_id;
 if found then raise exception using errcode='PT409',message='Траектория уже создана'; end if;
 if jsonb_typeof(p_steps) is distinct from 'array' or jsonb_array_length(p_steps) not between 1 and 30 or length(btrim(p_title)) not between 3 and 160
  or (p_auto_role is not null and p_auto_role not in ('worker','manager', 'director', 'hr_admin')) then raise exception using errcode='PT422',message='Проверьте название и шаги траектории'; end if;
 if p_auto_role is not null and exists(select 1 from learning_tracks where auto_role::text=p_auto_role) then raise exception using errcode='PT409',message='Для этой роли уже настроена автоматическая траектория'; end if;
 if (select count(distinct value->>'course_id') from jsonb_array_elements(p_steps))<>jsonb_array_length(p_steps) then raise exception using errcode='PT422',message='Курсы не должны повторяться'; end if;
 insert into learning_tracks(id,title,created_by,auto_role) values(p_id,btrim(p_title),p_actor_id,p_auto_role::app_role);
 for s in select value from jsonb_array_elements(p_steps) loop
  n:=n+1;
  if not exists(select 1 from courses where id=(s->>'course_id')::uuid and active) or coalesce((s->>'days_to_complete')::integer,0) not between 1 and 365 then raise exception using errcode='PT422',message='Выберите опубликованные курсы и срок 1–365 дней'; end if;
  insert into learning_track_steps values(p_id,n,(s->>'course_id')::uuid,(s->>'days_to_complete')::integer);
 end loop;
 return jsonb_build_object('id',p_id);
end $$;

create or replace function public.run_workflow_reminders() returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare p workflow_policy; r record; recipient uuid; count_sent integer:=0; escalated boolean; unavailable boolean; business_date date:=(now() at time zone 'Asia/Almaty')::date; advanced integer;
begin
 -- One scheduler transaction at a time, safe to run from multiple containers.
 if not pg_try_advisory_xact_lock(81102) then return jsonb_build_object('busy',true); end if;
 advanced:=advance_learning_tracks();
 select * into p from workflow_policy where id;
 if not p.enabled then update workflow_policy set last_run_at=now() where id; return jsonb_build_object('sent',0,'advanced',advanced); end if;
 for r in select q.id,q.employee_id,q.approver_ids,q.created_at from hr_requests q where status='pending' order by q.id for update skip locked loop
  select not exists(select 1 from employee_profiles ep where ep.id<>r.employee_id and ep.role in ('manager', 'director', 'hr_admin') and
   (ep.id=any(r.approver_ids) or exists(select 1 from approval_delegations d where d.deputy_id=ep.id and d.manager_id=any(r.approver_ids) and d.revoked_at is null and business_date between d.starts_on and d.ends_on))
   and not exists(select 1 from hr_requests l where l.employee_id=ep.id and l.request_type='leave' and l.status='approved' and business_date between l.start_date and l.end_date)) into unavailable;
  if not unavailable and r.created_at>now()-make_interval(hours=>p.remind_hours) then continue; end if;
  escalated:=unavailable or r.created_at<=now()-make_interval(hours=>p.escalate_hours);
  for recipient in select distinct ep.id from employee_profiles ep where ep.id<>r.employee_id and (
   (ep.id=any(r.approver_ids) and ep.role in ('manager', 'director', 'hr_admin')) or
   (ep.role in ('manager', 'director', 'hr_admin') and exists(select 1 from approval_delegations d where d.deputy_id=ep.id and d.manager_id=any(r.approver_ids) and d.revoked_at is null and business_date between d.starts_on and d.ends_on)) or
   (ep.role='hr_admin' and (escalated or not exists(select 1 from employee_profiles where id=any(r.approver_ids) and id<>r.employee_id and role in ('manager', 'director', 'hr_admin'))))) loop
   count_sent:=count_sent+notify_workflow_once('request:'||r.id||':'||case when escalated then 'escalation' else 'reminder' end,recipient,r.id,null,
    case when escalated then 'Согласование задерживается' else 'Заявка ожидает решения' end,'Откройте заявку. Если руководитель отсутствует, HR может принять решение или назначить заместителя.');
  end loop;
 end loop;
 for r in select f.request_id,f.updated_at,q.employee_id from request_fulfillment f join hr_requests q on q.id=f.request_id where f.status<>'completed' and f.updated_at<=now()-make_interval(hours=>p.remind_hours) order by f.request_id for update of f skip locked loop
  for recipient in select id from employee_profiles where role='hr_admin' and id<>r.employee_id loop
   count_sent:=count_sent+notify_workflow_once('fulfillment:'||r.request_id||':'||r.updated_at::text,recipient,r.request_id,null,'Оформление ожидает HR','Заявка согласована, документ ещё не оформлен.');
  end loop;
 end loop;
 for r in select ca.*,ep.manager_id,c.title from course_assignments ca join employee_profiles ep on ep.id=ca.employee_id join courses c on c.id=ca.course_id
  where ca.status<>'completed' and ca.due_on<=business_date+p.course_notice_days order by ca.id for update of ca skip locked loop
  escalated:=r.due_on<business_date;
  count_sent:=count_sent+notify_workflow_once('course:'||r.id||':'||r.due_on||':'||escalated,r.employee_id,null,r.course_id,
   case when escalated then 'Срок обучения истёк' else 'Подходит срок обучения' end,r.title||' · до '||r.due_on::text);
  if escalated then
   for recipient in select id from employee_profiles where id<>r.employee_id and (role='hr_admin' or (id=r.manager_id and role in ('manager','director'))) loop
    -- Team links carry no private course result or employee details.
    count_sent:=count_sent+notify_workflow_once('course:'||r.id||':'||r.due_on||':escalation',recipient,null,null,'Есть просроченное обучение','Откройте обучение команды и проверьте сроки.');
   end loop;
  end if;
 end loop;
 update workflow_policy set last_run_at=now() where id;
 return jsonb_build_object('sent',count_sent,'advanced',advanced);
end $$;
notify pgrst, 'reload schema';
commit;
