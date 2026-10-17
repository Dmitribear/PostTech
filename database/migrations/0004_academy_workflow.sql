-- Academy commands: material acknowledgement, scored attempts and notifications
-- are committed together. The 80% default is a prototype learning policy, not
-- an assertion about Jana Post's official personnel rules. Existing completed
-- assignments are preserved; the threshold applies to newly submitted quizzes.
begin;

alter table public.courses add column if not exists category text not null default 'Общее';
alter table public.courses add column if not exists audience text not null default 'Все сотрудники';
alter table public.courses add column if not exists passing_score integer not null default 80 check (passing_score between 1 and 100);
alter table public.course_assignments add column if not exists attempt_count integer not null default 0 check (attempt_count >= 0);
alter table public.course_assignments add column if not exists material_completed_at timestamptz;
alter table public.course_assignments add column if not exists last_attempt_at timestamptz;
alter table public.notifications add column if not exists course_id uuid references public.courses(id) on delete set null;

create table if not exists public.course_attempts (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references public.course_assignments(id) on delete cascade,
    submission_id uuid not null,
    attempt_number integer not null check (attempt_number > 0),
    answers jsonb not null,
    score_percent numeric(5,2) not null check (score_percent between 0 and 100),
    passed boolean not null,
    submitted_at timestamptz not null default now(),
    unique (assignment_id, submission_id),
    unique (assignment_id, attempt_number)
);
alter table public.course_attempts enable row level security;
create index if not exists course_attempts_assignment_idx on public.course_attempts(assignment_id, attempt_number desc);
create index if not exists notifications_course_idx on public.notifications(course_id) where course_id is not null;

create or replace function public.assign_academy_course(p_actor_id uuid, p_employee_id uuid, p_course_id uuid)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_actor public.employee_profiles%rowtype;
    v_employee public.employee_profiles%rowtype;
    v_course public.courses%rowtype;
    v_assignment public.course_assignments%rowtype;
begin
    select * into v_actor from public.employee_profiles where id = p_actor_id for share;
    if not found or v_actor.role not in ('manager', 'hr_admin') then
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
    select * into v_course from public.courses where id = p_course_id and active for share;
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
    select * into v_course from public.courses where id = p_course_id and active for share;
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

grant usage on schema public to service_role;
grant select on public.courses, public.employee_profiles to service_role;
-- PostgreSQL row locks also require UPDATE on at least one table column.
grant update(id) on public.courses, public.employee_profiles to service_role;
grant select, insert, update on public.course_assignments to service_role;
grant select, insert on public.course_attempts to service_role;
grant insert, select on public.notifications to service_role;
revoke all on public.course_attempts from anon, authenticated;
revoke execute on function public.assign_academy_course(uuid,uuid,uuid) from public, anon, authenticated;
revoke execute on function public.update_academy_progress(uuid,uuid,integer) from public, anon, authenticated;
revoke execute on function public.submit_academy_quiz(uuid,uuid,jsonb,uuid) from public, anon, authenticated;
grant execute on function public.assign_academy_course(uuid,uuid,uuid) to service_role;
grant execute on function public.update_academy_progress(uuid,uuid,integer) to service_role;
grant execute on function public.submit_academy_quiz(uuid,uuid,jsonb,uuid) to service_role;
notify pgrst, 'reload schema';
commit;
