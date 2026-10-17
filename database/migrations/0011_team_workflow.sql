-- Combined contract: manager/director -> HR, atomic final debit, pending holds.
-- Apply ONLY through database/migration-plan.json to a fresh isolated database.
-- Existing installations need a reviewed migration plan and balance reconciliation.
begin;

grant update(role) on public.employee_profiles to service_role;

alter table public.request_events drop constraint request_events_event_type_check;
alter table public.request_events add constraint request_events_event_type_check
 check(event_type in ('created','pending_hr','approved','rejected','cancelled'));
alter table public.request_events drop constraint request_event_transition_valid;
alter table public.request_events add constraint request_event_transition_valid check (
 (event_type='created' and from_status is null and to_status='pending')
 or (event_type='pending_hr' and from_status='pending' and to_status='pending_hr')
 or (event_type in ('approved','rejected','cancelled') and from_status in ('pending','pending_hr')
     and to_status::text=event_type)
);

drop index public.hr_requests_active_leave_idx;
create index hr_requests_active_leave_idx on public.hr_requests(employee_id,start_date,end_date)
 where request_type='leave' and status in ('pending','pending_hr','approved');

create or replace function public.review_hr_request(
 p_actor_id uuid,p_request_id uuid,p_status public.hr_request_status,p_reviewer_comment text
) returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare
 actor employee_profiles;
 req hr_requests;
 decision public.hr_request_status;
 previous public.hr_request_status;
 note text:=coalesce(p_reviewer_comment,'');
 delegation uuid;
 stage_reviewer uuid;
 stage_note text;
begin
 if p_status is null or p_status not in ('approved','rejected') then
  raise exception using errcode='PT422',message='Review status must be approved or rejected'; end if;
 if length(note)>2000 or (p_status='rejected' and note !~ '[^[:space:]]') then
  raise exception using errcode='PT422',message='A reason is required to reject a request (maximum 2000 characters)'; end if;
 select * into req from hr_requests where id=p_request_id for update;
 if not found then raise exception using errcode='PT404',message='Request not found'; end if;
 select * into actor from employee_profiles where id=p_actor_id;
 if not found then raise exception using errcode='PT404',message='Employee not found'; end if;
 if actor.role not in ('manager','director','hr_admin') then
  raise exception using errcode='PT403',message='Reviewer role required'; end if;
 if req.employee_id=p_actor_id then
  raise exception using errcode='PT403',message='You cannot review your own request'; end if;

 if actor.role in ('manager','director') then
  stage_reviewer:=coalesce(req.manager_reviewed_by,req.director_reviewed_by);
  stage_note:=coalesce(req.manager_reviewer_comment,req.director_reviewer_comment,'');
  -- A retry of an already recorded first-stage approval cannot debit or notify again,
  -- including when HR has since finished the request.
  if stage_reviewer=p_actor_id and stage_note=note and (
      (p_status='approved' and req.status in ('pending_hr','approved','rejected','cancelled')
       and exists(select 1 from request_events where request_id=req.id and event_type='pending_hr' and actor_id=p_actor_id))
      or (p_status='rejected' and req.status='rejected' and req.reviewed_by=p_actor_id)) then
   return to_jsonb(req)-'idempotency_key'-'approver_ids';
  end if;
  if not (p_actor_id=any(req.approver_ids)) then
   select d.id into delegation from approval_delegations d
    where d.deputy_id=p_actor_id and d.manager_id=any(req.approver_ids)
      and d.manager_id in (select active_delegation_principals(p_actor_id))
      and d.revoked_at is null and (now() at time zone 'Asia/Qyzylorda')::date between d.starts_on and d.ends_on
    order by d.created_at desc limit 1;
   if delegation is null then raise exception using errcode='PT403',message='You are not an assigned approver for this request'; end if;
  end if;
  if req.status<>'pending' or req.approval_route<>'manager' then
   raise exception using errcode='PT409',message='Only requests awaiting the assigned supervisor can be reviewed'; end if;
  decision:=case when p_status='approved' then 'pending_hr' else 'rejected' end;
  if decision='pending_hr' and not exists(select 1 from employee_profiles where role='hr_admin' and id<>req.employee_id) then
   raise exception using errcode='PT409',message='No eligible HR reviewer is configured'; end if;
 else
  if req.status not in ('pending','pending_hr') then
   if req.status=p_status and req.reviewed_by=p_actor_id and coalesce(req.reviewer_comment,'')=note then
    return to_jsonb(req)-'idempotency_key'-'approver_ids'; end if;
   raise exception using errcode='PT409',message='Request is no longer pending';
  end if;
  if req.status='pending' and req.approval_route='manager' then
   raise exception using errcode='PT409',message='Supervisor review is required before HR review'; end if;
  decision:=p_status;
 end if;

 previous:=req.status;
 update hr_requests set status=decision,
  manager_reviewed_by=case when actor.role='manager' then p_actor_id else manager_reviewed_by end,
  manager_reviewed_at=case when actor.role='manager' then now() else manager_reviewed_at end,
  manager_reviewer_comment=case when actor.role='manager' then p_reviewer_comment else manager_reviewer_comment end,
  director_reviewed_by=case when actor.role='director' then p_actor_id else director_reviewed_by end,
  director_reviewed_at=case when actor.role='director' then now() else director_reviewed_at end,
  director_reviewer_comment=case when actor.role='director' then p_reviewer_comment else director_reviewer_comment end,
  hr_reviewed_by=case when actor.role='hr_admin' then p_actor_id else hr_reviewed_by end,
  hr_reviewed_at=case when actor.role='hr_admin' then now() else hr_reviewed_at end,
  hr_reviewer_comment=case when actor.role='hr_admin' then p_reviewer_comment else hr_reviewer_comment end,
  reviewed_by=case when decision<>'pending_hr' then p_actor_id else null end,
  reviewed_at=case when decision<>'pending_hr' then now() else null end,
  reviewer_comment=case when decision<>'pending_hr' then p_reviewer_comment else null end
 where id=p_request_id returning * into req;
 insert into request_events(request_id,actor_id,event_type,from_status,to_status,comment,delegation_id)
 values(req.id,p_actor_id,decision::text,previous,decision,note,delegation);
 insert into notifications(employee_id,request_id,notification_type,title,body)
 values(req.employee_id,req.id,
  case when decision='pending_hr' then 'request_pending_hr' else 'request_status_changed' end,
  'Статус заявки изменён',
  case when decision='pending_hr' then 'Руководитель согласовал заявку. Ожидается окончательное решение HR.'
   when decision='rejected' then 'Заявка отклонена. Причина: '||note else 'Заявка окончательно одобрена HR.' end);
 if decision='pending_hr' then
  insert into notifications(employee_id,request_id,notification_type,title,body)
  select id,req.id,'request_pending_hr','Заявка ожидает HR','Руководитель согласовал заявку. Требуется окончательное решение HR.'
   from employee_profiles where role='hr_admin' and id<>req.employee_id;
 end if;
 return to_jsonb(req)-'idempotency_key'-'approver_ids';
end $$;

create or replace function public.cancel_hr_request(p_actor_id uuid,p_request_id uuid)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare req hr_requests; previous public.hr_request_status;
begin
 select * into req from hr_requests where id=p_request_id for update;
 if not found then raise exception using errcode='PT404',message='Request not found'; end if;
 if p_actor_id is null or req.employee_id<>p_actor_id then
  raise exception using errcode='PT403',message='Only the owner can cancel a request'; end if;
 if req.status='cancelled' then return to_jsonb(req)-'idempotency_key'-'approver_ids'; end if;
 if req.status not in ('pending','pending_hr') then
  raise exception using errcode='PT409',message='Only requests awaiting approval can be cancelled'; end if;
 previous:=req.status;
 update hr_requests set status='cancelled',cancelled_at=now() where id=req.id returning * into req;
 insert into request_events(request_id,actor_id,event_type,from_status,to_status,comment)
 values(req.id,p_actor_id,'cancelled',previous,'cancelled','Отозвана автором');
 insert into notifications(employee_id,request_id,notification_type,title,body)
 select id,req.id,'request_cancelled','Заявка отозвана','Автор отозвал заявку. Согласование больше не требуется.'
 from employee_profiles where id=p_actor_id or id=any(req.approver_ids) or (previous='pending_hr' and role='hr_admin');
 return to_jsonb(req)-'idempotency_key'-'approver_ids';
end $$;

create or replace function public.track_request_extensions()
returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare official numeric; held numeric;
begin
 if new.request_type='leave' then
  select vacation_days_remaining into official from employee_profiles where id=new.employee_id for update;
  if tg_op='INSERT' and new.status='pending' then
   select coalesce(sum(days),0) into held from leave_holds where employee_id=new.employee_id and state in ('pending','approved');
   if new.leave_days>official-held then
    raise exception using errcode='PT409',message='Недостаточно дней отпуска с учётом других заявок'; end if;
   insert into leave_holds(request_id,employee_id,days,state) values(new.id,new.employee_id,new.leave_days,'pending');
  elsif tg_op='UPDATE' and new.status is distinct from old.status then
   -- Main's debit trigger has already deducted on final approval. Reconciled
   -- holds are excluded from available_days, so no second subtraction occurs.
   update leave_holds set state=case when new.status='approved' then 'reconciled'
       when new.status in ('pending','pending_hr') then 'pending' else 'released' end,updated_at=now()
    where request_id=new.id and state='pending';
  end if;
 end if;
 if tg_op='UPDATE' and new.status='approved' and old.status<>'approved' then
  insert into integration_outbox(destination,event_key,event_type,aggregate_id,payload)
  select d,new.id::text||':approved:v1','request.approved',new.id,
   jsonb_build_object('schema_version',1,'request_id',new.id,'employee_id',new.employee_id,
    'request_type',new.request_type,'start_date',new.start_date,'end_date',new.end_date,
    'amount',new.amount,'reviewed_by',new.reviewed_by,'reviewed_at',new.reviewed_at)
  from unnest(array['1c','documentolog']) d on conflict(destination,event_key) do nothing;
 end if;
 return new;
end $$;

-- Additional role-compatible definitions are appended below, preserving the
-- original transaction logic from test and only broadening supervisor roles.
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
            v_route := case when v_manager.role='hr_admin' then 'hr' else 'manager' end;
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
        'policy', 'MVP: inclusive calendar days; no past start dates; pending, pending HR and approved leave periods must not overlap; final HR approval deducts the balance once; pending requests reserve days.'
    );
end;
$$;

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
                and status in ('pending', 'pending_hr', 'approved')
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
        perform id from public.employee_profiles where id=v_manager and role in ('manager','director','hr_admin') for share;
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
            and auth_user_id<>p_auth_user_id and role in ('manager','director','hr_admin') for share;
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
 join employee_profiles e on e.id=d.deputy_id and e.role in ('manager','director')
 join employee_profiles primary_manager on primary_manager.id=d.manager_id and primary_manager.role in ('manager','director')
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
 -- HR owns the final stage. Keeping deputies in supervisor roles makes an
 -- identical first-stage retry unambiguous and prevents accidental final approval.
 if (select count(*) from employee_profiles where id in (p_manager_id,p_deputy_id) and role in ('manager','director'))<>2 then
  raise exception using errcode='PT422',message='First-stage delegation requires two managers or directors'; end if;
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

create or replace function public.reconcile_leave_balance(p_actor_id uuid,p_id uuid,p_employee_id uuid,p_days numeric,p_requests uuid[],p_note text)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare previous leave_balance_events; result leave_balance_events;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 if p_days is null or p_days<0 or p_days>999 or length(btrim(coalesce(p_note,'')))<3 then raise exception using errcode='PT422',message='Balance and reconciliation reference required'; end if;
 perform 1 from employee_profiles where id=p_employee_id for update;
 if not found then raise exception using errcode='PT404',message='Employee not found'; end if;
 select * into previous from leave_balance_events where id=p_id;
 if found then
  if previous.employee_id<>p_employee_id or previous.official_days<>p_days or previous.covered_requests is distinct from p_requests or previous.note<>p_note then raise exception using errcode='PT409',message='Reconciliation key already used'; end if;
  return to_jsonb(previous);
 end if;
 if p_requests is null or cardinality(p_requests)<>(select count(*) from leave_holds where employee_id=p_employee_id and state='approved' and request_id=any(p_requests)) then
  raise exception using errcode='PT409',message='Select only unreconciled approved requests'; end if;
 if p_days < (select coalesce(sum(days),0) from leave_holds where employee_id=p_employee_id and (state='pending' or (state='approved' and not request_id=any(p_requests)))) then
  raise exception using errcode='PT409',message='Balance cannot be lower than outstanding leave reservations'; end if;
 update employee_profiles set vacation_days_remaining=p_days where id=p_employee_id;
 update leave_holds set state='reconciled',updated_at=now() where request_id=any(p_requests);
 insert into leave_balance_events values(p_id,p_employee_id,p_actor_id,p_days,p_requests,p_note,now()) returning * into result;
 return to_jsonb(result);
end $$;

notify pgrst, 'reload schema';
commit;
