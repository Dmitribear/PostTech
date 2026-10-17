-- Approval is a decision; fulfillment records the document separately.
begin;
alter table public.integration_outbox drop constraint integration_outbox_status_check;
alter table public.integration_outbox add constraint integration_outbox_status_check check(status in ('queued','sending','retry','delivered','dead','cancelled'));
create table public.request_fulfillment (
 request_id uuid primary key references public.hr_requests(id) on delete cascade,
 status text not null default 'awaiting_hr' check(status in ('awaiting_hr','processing','completed')),
 started_by uuid references public.employee_profiles(id), started_at timestamptz,
 completed_by uuid references public.employee_profiles(id), completed_at timestamptz,
 document_reference text, note text not null default '', updated_at timestamptz not null default now()
);
create table public.fulfillment_events (
 id uuid primary key default gen_random_uuid(), request_id uuid not null references public.hr_requests(id),
 actor_id uuid references public.employee_profiles(id), action text not null, detail text not null default '',
 created_at timestamptz not null default now()
);
insert into public.request_fulfillment(request_id,status,started_at)
 select r.id,case when exists(select 1 from public.integration_outbox o where o.aggregate_id=r.id) then 'processing' else 'awaiting_hr' end,
 case when exists(select 1 from public.integration_outbox o where o.aggregate_id=r.id) then r.reviewed_at end
 from public.hr_requests r where r.status='approved';

create or replace function public.track_request_extensions() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare official numeric; held numeric;
begin
 if new.request_type='leave' then
  select vacation_days_remaining into official from employee_profiles where id=new.employee_id for update;
  if tg_op='INSERT' and new.status='pending' then
   select coalesce(sum(days),0) into held from leave_holds where employee_id=new.employee_id and state in ('pending','approved');
   if new.end_date-new.start_date+1 > official-held then raise exception using errcode='PT409',message='Недостаточно дней отпуска с учётом других заявок'; end if;
   insert into leave_holds(request_id,employee_id,days,state) values(new.id,new.employee_id,new.end_date-new.start_date+1,'pending');
  elsif tg_op='UPDATE' and new.status is distinct from old.status then
   -- Final approval already debits the official balance in main's trigger.
   -- Keep first-stage reservations; remove the hold from availability only once.
   update leave_holds set state=case when new.status='approved' then 'reconciled'
       when new.status in ('pending','pending_hr') then 'pending' else 'released' end,
       updated_at=now() where request_id=new.id and state='pending';
  end if;
 end if;
 if tg_op='UPDATE' and new.status='approved' and old.status<>'approved' then
  insert into request_fulfillment(request_id) values(new.id) on conflict do nothing;
  insert into fulfillment_events(request_id,action) values(new.id,'awaiting_hr');
  insert into notifications(employee_id,request_id,notification_type,title,body)
   select id,new.id,'fulfillment','Заявка согласована — требуется оформление','Проверьте заявку и оформите документ.' from employee_profiles where role='hr_admin' and id<>new.employee_id;
 end if;
 return new;
end $$;

create function public.fulfill_hr_request(p_actor_id uuid,p_request_id uuid,p_action text,p_reference text default '',p_note text default '') returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare r hr_requests; f request_fulfillment;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 select * into r from hr_requests where id=p_request_id for update;
 if not found then raise exception using errcode='PT404',message='Request not found'; end if;
 if r.employee_id=p_actor_id then raise exception using errcode='PT403',message='Свою заявку должен оформить другой HR'; end if;
 if r.status<>'approved' then raise exception using errcode='PT409',message='Сначала необходимо согласование'; end if;
 select * into f from request_fulfillment where request_id=r.id for update;
 if not found then raise exception using errcode='PT409',message='Этап оформления не найден'; end if;
 if p_action not in ('start','complete') or p_action is null then raise exception using errcode='PT422',message='Неизвестное действие'; end if;
 if f.status='completed' then
  if p_action='complete' and f.document_reference=btrim(p_reference) and f.note=btrim(p_note) then return to_jsonb(f); end if;
  raise exception using errcode='PT409',message='Документ уже оформлен';
 end if;
 if p_action='start' then
  if f.status='processing' then return to_jsonb(f); end if;
  update request_fulfillment set status='processing',started_by=p_actor_id,started_at=now(),updated_at=now() where request_id=r.id returning * into f;
  insert into integration_outbox(destination,event_key,event_type,aggregate_id,payload)
   select d,r.id::text||':approved:v1','request.approved',r.id,
    jsonb_build_object('schema_version',1,'request_id',r.id,'employee_id',r.employee_id,'request_type',r.request_type,
      'start_date',r.start_date,'end_date',r.end_date,'amount',r.amount,'reviewed_by',r.reviewed_by,'reviewed_at',r.reviewed_at)
   from unnest(array['1c','documentolog']) d on conflict(destination,event_key) do nothing;
 else
  if length(btrim(coalesce(p_reference,''))) not between 3 and 200 or length(coalesce(p_note,''))>2000 then raise exception using errcode='PT422',message='Укажите номер оформленного документа (3–200 символов)'; end if;
  perform id from integration_outbox where aggregate_id=r.id order by id for update;
  -- A legacy event never attempted can be superseded by a manual document.
  -- Anything possibly accepted by a receiver must be resolved there first.
  if not exists(select 1 from integration_outbox where aggregate_id=r.id and (status<>'queued' or attempts<>0)) then
   insert into integration_attempts(event_id,attempt,outcome,detail,actor_id)
    select id,0,'manual_document','Unsent event replaced by a manually recorded document',p_actor_id from integration_outbox where aggregate_id=r.id;
   update integration_outbox set status='cancelled',last_error='Оформлено вручную до отправки' where aggregate_id=r.id;
  end if;
  if exists(select 1 from integration_outbox where aggregate_id=r.id and status not in ('delivered','cancelled')) then
   raise exception using errcode='PT409',message='Передача ещё не завершена. Проверьте очередь интеграций'; end if;
  update request_fulfillment set status='completed',completed_by=p_actor_id,completed_at=now(),document_reference=btrim(p_reference),note=btrim(p_note),updated_at=now() where request_id=r.id returning * into f;
 end if;
 insert into fulfillment_events(request_id,actor_id,action,detail) values(r.id,p_actor_id,p_action,case when p_action='complete' then btrim(p_reference) else '' end);
 insert into notifications(employee_id,request_id,notification_type,title,body) values(r.employee_id,r.id,'fulfillment',
  case when p_action='complete' then 'Заявка оформлена' else 'HR начал оформление' end,
  case when p_action='complete' then 'Документ: '||btrim(p_reference) else 'Согласование завершено. HR готовит документ.' end);
 return to_jsonb(f);
end $$;

create table public.learning_tracks (
 id uuid primary key, title text not null check(length(btrim(title)) between 3 and 160),
 created_by uuid not null references public.employee_profiles(id), created_at timestamptz not null default now(),
 active boolean not null default true, auto_role public.app_role unique
);
create table public.learning_track_steps (
 track_id uuid not null references public.learning_tracks(id), position integer not null check(position between 1 and 30),
 course_id uuid not null references public.courses(id), days_to_complete integer not null check(days_to_complete between 1 and 365),
 primary key(track_id,position), unique(track_id,course_id)
);
create table public.learning_enrollments (
 id uuid primary key default gen_random_uuid(), track_id uuid not null references public.learning_tracks(id),
 employee_id uuid not null references public.employee_profiles(id), assigned_by uuid not null references public.employee_profiles(id),
 enrolled_at timestamptz not null default now(), completed_at timestamptz, unique(track_id,employee_id)
);
create function public.create_learning_track(p_actor_id uuid,p_id uuid,p_title text,p_steps jsonb,p_auto_role text default null) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare s jsonb; n integer:=0; old learning_tracks;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 perform pg_advisory_xact_lock(81101);
 select * into old from learning_tracks where id=p_id;
 if found then raise exception using errcode='PT409',message='Траектория уже создана'; end if;
 if jsonb_typeof(p_steps) is distinct from 'array' or jsonb_array_length(p_steps) not between 1 and 30 or length(btrim(p_title)) not between 3 and 160
  or (p_auto_role is not null and p_auto_role not in ('worker','manager','director','hr_admin')) then raise exception using errcode='PT422',message='Проверьте название и шаги траектории'; end if;
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

-- Only the first incomplete course is assigned. Existing completed learning is credited.
create function public.advance_learning_tracks(p_employee_id uuid default null) returns integer
language plpgsql security invoker set search_path=public,pg_temp as $$
declare e learning_enrollments; s record; a course_assignments; created uuid; changes integer:=0;
begin
 for e in select * from learning_enrollments where completed_at is null and (p_employee_id is null or employee_id=p_employee_id) order by id for update skip locked loop
  select st.*,c.title into s from learning_track_steps st join courses c on c.id=st.course_id
   where st.track_id=e.track_id and not exists(select 1 from course_assignments ca where ca.employee_id=e.employee_id and ca.course_id=st.course_id and ca.status='completed') order by position limit 1;
  if not found then update learning_enrollments set completed_at=now() where id=e.id; changes:=changes+1; continue; end if;
  created:=null;
  insert into course_assignments(employee_id,course_id,assigned_by,due_on)
   values(e.employee_id,s.course_id,e.assigned_by,(now() at time zone 'Asia/Almaty')::date+s.days_to_complete)
   on conflict(employee_id,course_id) do nothing returning id into created;
  if created is not null then
   changes:=changes+1;
   insert into notifications(employee_id,course_id,notification_type,title,body) values(e.employee_id,s.course_id,'course_assigned','Следующий шаг адаптации',s.title);
  else
   update course_assignments set due_on=(now() at time zone 'Asia/Almaty')::date+s.days_to_complete
    where employee_id=e.employee_id and course_id=s.course_id and due_on is null and status<>'completed';
  end if;
 end loop;
 return changes;
end $$;
create function public.enroll_learning_track(p_actor_id uuid,p_track_id uuid,p_employee_id uuid) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare e learning_enrollments;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 perform 1 from learning_tracks where id=p_track_id and active for share;
 if not found then raise exception using errcode='PT404',message='Траектория недоступна'; end if;
 if not exists(select 1 from employee_profiles where id=p_employee_id) then raise exception using errcode='PT404',message='Employee not found'; end if;
 insert into learning_enrollments(track_id,employee_id,assigned_by) values(p_track_id,p_employee_id,p_actor_id) on conflict do nothing;
 perform advance_learning_tracks(p_employee_id);
 select * into e from learning_enrollments where track_id=p_track_id and employee_id=p_employee_id;
 return to_jsonb(e);
end $$;
create function public.onboard_learning_track() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
begin
 insert into learning_enrollments(track_id,employee_id,assigned_by) select id,new.id,created_by from learning_tracks where active and auto_role=new.role on conflict do nothing;
 perform advance_learning_tracks(new.id);
 return new;
end $$;
create trigger onboard_learning after insert on public.employee_profiles for each row execute function public.onboard_learning_track();

create table public.workflow_policy (
 id boolean primary key default true check(id), enabled boolean not null default true,
 remind_hours integer not null default 48 check(remind_hours between 1 and 720),
 escalate_hours integer not null default 96 check(escalate_hours between 2 and 1440),
 course_notice_days integer not null default 3 check(course_notice_days between 0 and 30),
 updated_by uuid references public.employee_profiles(id), updated_at timestamptz not null default now(),
 last_run_at timestamptz, check(escalate_hours>remind_hours)
);
insert into public.workflow_policy(id) values(true);
create table public.workflow_reminders (
 dedupe_key text primary key, employee_id uuid not null references public.employee_profiles(id),
 created_at timestamptz not null default now()
);
create function public.notify_workflow_once(p_key text,p_employee_id uuid,p_request_id uuid,p_course_id uuid,p_title text,p_body text) returns integer
language plpgsql security invoker set search_path=public,pg_temp as $$
begin
 insert into workflow_reminders(dedupe_key,employee_id) values(p_key||':'||p_employee_id::text,p_employee_id) on conflict do nothing;
 if not found then return 0; end if;
 insert into notifications(employee_id,request_id,course_id,notification_type,title,body) values(p_employee_id,p_request_id,p_course_id,
  case when p_course_id is not null then 'course_reminder' when p_key like 'course:%' then 'team_training_reminder' else 'workflow_reminder' end,p_title,p_body);
 return 1;
end $$;
create function public.run_workflow_reminders() returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare p workflow_policy; r record; recipient uuid; count_sent integer:=0; escalated boolean; unavailable boolean; business_date date:=(now() at time zone 'Asia/Almaty')::date; advanced integer;
begin
 -- One scheduler transaction at a time, safe to run from multiple containers.
 if not pg_try_advisory_xact_lock(81102) then return jsonb_build_object('busy',true); end if;
 advanced:=advance_learning_tracks();
 select * into p from workflow_policy where id;
 if not p.enabled then update workflow_policy set last_run_at=now() where id; return jsonb_build_object('sent',0,'advanced',advanced); end if;
 for r in select q.id,q.employee_id,q.approver_ids,q.status,
   case when q.status='pending_hr' then coalesce(q.manager_reviewed_at,q.director_reviewed_at,q.created_at) else q.created_at end as stage_started_at
   from hr_requests q where status in ('pending','pending_hr') order by q.id for update skip locked loop
  select not exists(select 1 from employee_profiles ep where ep.id<>r.employee_id and
   ((r.status='pending_hr' and ep.role='hr_admin') or (r.status='pending' and
    ((ep.id=any(r.approver_ids) and ep.role in ('manager','director','hr_admin')) or
     (ep.role in ('manager','director') and exists(select 1 from active_delegation_principals(ep.id) principal where principal=any(r.approver_ids))))))
   and not exists(select 1 from hr_requests l where l.employee_id=ep.id and l.request_type='leave' and l.status='approved' and business_date between l.start_date and l.end_date)) into unavailable;
  if not unavailable and r.stage_started_at>now()-make_interval(hours=>p.remind_hours) then continue; end if;
  escalated:=unavailable or r.stage_started_at<=now()-make_interval(hours=>p.escalate_hours);
  for recipient in select distinct ep.id from employee_profiles ep where ep.id<>r.employee_id and (
   (r.status='pending_hr' and ep.role='hr_admin') or
   (r.status='pending' and ((ep.id=any(r.approver_ids) and ep.role in ('manager','director','hr_admin')) or
    (ep.role in ('manager','director') and exists(select 1 from active_delegation_principals(ep.id) principal where principal=any(r.approver_ids))) or
    (ep.role='hr_admin' and escalated)))) loop
   count_sent:=count_sent+notify_workflow_once('request:'||r.id||':'||r.status||':'||case when escalated then 'escalation' else 'reminder' end,recipient,r.id,null,
    case when escalated then 'Согласование задерживается' else 'Заявка ожидает решения' end,'Откройте заявку. HR может проверить маршрут или назначить допустимого заместителя. Напоминание не меняет статус заявки.');
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

do $$ declare t text; f regprocedure; begin
 foreach t in array array['request_fulfillment','fulfillment_events','learning_tracks','learning_track_steps','learning_enrollments','workflow_policy','workflow_reminders'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
 end loop;
 for f in select oid::regprocedure from pg_proc where pronamespace='public'::regnamespace and proname in ('fulfill_hr_request','create_learning_track','advance_learning_tracks','enroll_learning_track','onboard_learning_track','notify_workflow_once','run_workflow_reminders') loop
  execute format('revoke all on function %s from public,anon,authenticated',f);
  execute format('grant execute on function %s to service_role',f);
 end loop;
end $$;
notify pgrst,'reload schema';
commit;
