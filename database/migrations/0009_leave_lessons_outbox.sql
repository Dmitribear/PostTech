-- Official balance is a snapshot. Local holds are separate and never debit it twice.
begin;
create table public.leave_holds (
 request_id uuid primary key references public.hr_requests(id) on delete cascade,
 employee_id uuid not null references public.employee_profiles(id),
 days integer not null check(days>0),
 state text not null check(state in ('pending','approved','released','reconciled')),
 updated_at timestamptz not null default now()
);
create index leave_holds_employee on public.leave_holds(employee_id,state);
insert into public.leave_holds(request_id,employee_id,days,state)
 select id,employee_id,end_date-start_date+1,'pending' from public.hr_requests where request_type='leave' and status='pending';
-- Historical approvals may already be in the imported balance; do not guess.
create table public.leave_balance_events (
 id uuid primary key, employee_id uuid not null references public.employee_profiles(id),
 actor_id uuid not null references public.employee_profiles(id),
 official_days numeric not null, covered_requests uuid[] not null, note text not null,
 created_at timestamptz not null default now()
);

create table public.integration_outbox (
 id uuid primary key default gen_random_uuid(),
 destination text not null check(destination in ('1c','documentolog')),
 event_key text not null, event_type text not null, aggregate_id uuid not null,
 payload jsonb not null, status text not null default 'queued'
 check(status in ('queued','sending','retry','delivered','dead')),
 attempts integer not null default 0, next_attempt_at timestamptz not null default now(),
 lease_token uuid, lease_until timestamptz, last_error text,
 delivered_at timestamptz, created_at timestamptz not null default now(),
 unique(destination,event_key)
);
create index outbox_ready on public.integration_outbox(destination,next_attempt_at) where status in ('queued','retry','sending');
create table public.integration_attempts (
 id uuid primary key default gen_random_uuid(), event_id uuid not null references public.integration_outbox(id),
 attempt integer not null, outcome text not null, detail text, actor_id uuid,
 created_at timestamptz not null default now()
);

create function public.track_request_extensions() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare official numeric; held numeric;
begin
 if new.request_type='leave' then
  select vacation_days_remaining into official from employee_profiles where id=new.employee_id for update;
  if tg_op='INSERT' and new.status='pending' then
   select coalesce(sum(days),0) into held from leave_holds where employee_id=new.employee_id and state in ('pending','approved');
   if new.end_date-new.start_date+1 > official-held then
    raise exception using errcode='PT409',message='Недостаточно дней отпуска с учётом других заявок'; end if;
   insert into leave_holds(request_id,employee_id,days,state) values(new.id,new.employee_id,new.end_date-new.start_date+1,'pending');
  elsif tg_op='UPDATE' and new.status is distinct from old.status then
   update leave_holds set state=case when new.status='approved' then 'approved' else 'released' end,updated_at=now()
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
create trigger request_extensions after insert or update of status on public.hr_requests for each row execute function public.track_request_extensions();

create function public.reconcile_leave_balance(p_actor_id uuid,p_id uuid,p_employee_id uuid,p_days numeric,p_requests uuid[],p_note text)
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
 update employee_profiles set vacation_days_remaining=p_days where id=p_employee_id;
 update leave_holds set state='reconciled',updated_at=now() where request_id=any(p_requests);
 insert into leave_balance_events values(p_id,p_employee_id,p_actor_id,p_days,p_requests,p_note,now()) returning * into result;
 return to_jsonb(result);
end $$;

create function public.claim_integration_event(p_destination text,p_lease_seconds integer default 60) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare item integration_outbox;
begin
 if p_lease_seconds not between 30 and 300 then raise exception using errcode='PT422',message='Invalid lease'; end if;
 select * into item from integration_outbox where destination=p_destination and attempts<8 and
 ((status in ('queued','retry') and next_attempt_at<=now()) or (status='sending' and lease_until<now()))
 order by next_attempt_at,id for update skip locked limit 1;
 if not found then
  update integration_outbox set status='dead',last_error='Delivery outcome unknown after expired lease',lease_token=null,lease_until=null
   where destination=p_destination and status='sending' and attempts>=8 and lease_until<now();
  return null;
 end if;
 if item.status='sending' then insert into integration_attempts(event_id,attempt,outcome,detail) values(item.id,item.attempts,'lease_expired','Receiver may have accepted this event; retry uses the same idempotency key'); end if;
 update integration_outbox set status='sending',attempts=attempts+1,lease_token=gen_random_uuid(),lease_until=now()+make_interval(secs=>p_lease_seconds)
 where id=item.id returning * into item;
 return to_jsonb(item);
end $$;
create function public.finish_integration_event(p_id uuid,p_token uuid,p_success boolean,p_error text default null) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare item integration_outbox;
begin
 select * into item from integration_outbox where id=p_id for update;
 if not found then raise exception using errcode='PT404',message='Event not found'; end if;
 if item.status<>'sending' or item.lease_token is distinct from p_token then raise exception using errcode='PT409',message='Stale delivery lease'; end if;
 insert into integration_attempts(event_id,attempt,outcome,detail) values(p_id,item.attempts,case when p_success then 'accepted' else 'failed' end,left(p_error,250));
 update integration_outbox set status=case when p_success then 'delivered' when attempts>=8 then 'dead' else 'retry' end,
  delivered_at=case when p_success then now() else null end,last_error=case when p_success then null else left(p_error,250) end,
  next_attempt_at=now()+make_interval(secs=>least(3600,(30*power(2,least(attempts,7)))::int)),lease_token=null,lease_until=null
 where id=p_id returning * into item;
 return to_jsonb(item);
end $$;
create function public.retry_integration_event(p_actor_id uuid,p_id uuid) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare item integration_outbox;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 select * into item from integration_outbox where id=p_id for update;
 if not found then raise exception using errcode='PT404',message='Event not found'; end if;
 if item.status not in ('dead','retry') then raise exception using errcode='PT409',message='Only failed delivery can be retried'; end if;
 insert into integration_attempts(event_id,attempt,outcome,actor_id) values(p_id,item.attempts,'manual_retry',p_actor_id);
 update integration_outbox set status='queued',attempts=0,next_attempt_at=now(),last_error=null where id=p_id returning * into item;
 return to_jsonb(item);
end $$;

alter table public.courses add column lessons jsonb not null default '[]' check(jsonb_typeof(lessons)='array' and jsonb_array_length(lessons)<=50);
alter table public.course_assignments add column completed_lesson_ids text[] not null default '{}';
alter function public.edit_academy_course(uuid,uuid,text,integer,jsonb) rename to edit_academy_course_v8;
create function public.edit_academy_course(p_actor_id uuid,p_id uuid,p_action text,p_revision integer,p_data jsonb) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare result jsonb; lesson jsonb; lessons_value jsonb:=coalesce(p_data->'lessons','[]'); existed boolean;
begin
 perform pg_advisory_xact_lock(81008);
 select exists(select 1 from courses where id=p_id) into existed;
 if p_action in ('create','save') then
  if jsonb_typeof(lessons_value)<>'array' or jsonb_array_length(lessons_value)>50 then raise exception using errcode='PT422',message='Invalid lessons'; end if;
  if (select count(distinct x->>'id') from jsonb_array_elements(lessons_value) x)<>jsonb_array_length(lessons_value) then raise exception using errcode='PT422',message='Lesson IDs must be unique'; end if;
  for lesson in select value from jsonb_array_elements(lessons_value) loop
   if coalesce(lesson->>'id','') !~ '^[a-zA-Z0-9_-]{1,80}$' or length(btrim(coalesce(lesson->>'title','')))<3 or length(btrim(coalesce(lesson->>'material_markdown','')))<3 then raise exception using errcode='PT422',message='Each lesson needs ID, title and material'; end if;
  end loop;
 end if;
 result:=edit_academy_course_v8(p_actor_id,p_id,p_action,p_revision,p_data);
 if p_action='save' or (p_action='create' and not existed) then
  update courses set lessons=lessons_value where id=p_id;
 end if;
 select to_jsonb(c) into result from courses c where id=p_id;
 return result;
end $$;
create function public.guard_lesson_progress() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare lesson_ids text[];
begin
 select array_agg(x->>'id') into lesson_ids from courses c cross join lateral jsonb_array_elements(c.lessons) x where c.id=new.course_id;
 if cardinality(lesson_ids)>0 and (not new.completed_lesson_ids <@ lesson_ids or (new.progress_percent>=90 and not lesson_ids <@ new.completed_lesson_ids)) then
  raise exception using errcode='PT409',message='Сначала завершите все уроки курса'; end if;
 return new;
end $$;
create trigger guard_lesson_progress before insert or update on public.course_assignments for each row execute function public.guard_lesson_progress();
create function public.complete_academy_lesson(p_actor_id uuid,p_course_id uuid,p_lesson_id text) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare a course_assignments; lesson_ids text[]; done text[]; percent integer;
begin
 select * into a from course_assignments where course_id=p_course_id and employee_id=p_actor_id for update;
 if not found then raise exception using errcode='PT404',message='Course assignment not found'; end if;
 select array_agg(x->>'id') into lesson_ids from courses c cross join lateral jsonb_array_elements(c.lessons) x where c.id=p_course_id;
 if lesson_ids is null or not p_lesson_id=any(lesson_ids) then raise exception using errcode='PT404',message='Lesson not found'; end if;
 if a.status='completed' or p_lesson_id=any(a.completed_lesson_ids) then return to_jsonb(a); end if;
 done:=array_append(a.completed_lesson_ids,p_lesson_id); percent:=floor(90.0*cardinality(done)/cardinality(lesson_ids));
 update course_assignments set completed_lesson_ids=done,progress_percent=percent,status='in_progress',
 material_completed_at=case when percent=90 then coalesce(material_completed_at,now()) else null end
 where id=a.id returning * into a;
 return to_jsonb(a);
end $$;

do $$ declare n text; f record; begin
 foreach n in array array['leave_holds','leave_balance_events','integration_outbox','integration_attempts'] loop
  execute format('alter table public.%I enable row level security',n);
  execute format('revoke all on public.%I from anon,authenticated',n);
  execute format('grant all on public.%I to service_role',n);
 end loop;
 for f in select oid::regprocedure signature from pg_proc where pronamespace='public'::regnamespace and proname in
 ('track_request_extensions','reconcile_leave_balance','claim_integration_event','finish_integration_event','retry_integration_event','edit_academy_course','guard_lesson_progress','complete_academy_lesson') loop
  execute format('revoke execute on function %s from public,anon,authenticated',f.signature);
  execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
grant update(vacation_days_remaining) on public.employee_profiles to service_role;
-- One statement gives a consistent balance/holds snapshot during reconciliation.
create function public.read_leave_balance(p_employee_id uuid) returns jsonb language sql security invoker set search_path=public,pg_temp as $$
 select jsonb_build_object('employee_id',p.id,'official_days',p.vacation_days_remaining,
  'pending_days',coalesce(h.pending,0),'approved_unreconciled_days',coalesce(h.approved,0),
  'available_days',p.vacation_days_remaining-coalesce(h.pending,0)-coalesce(h.approved,0),
  'holds',coalesce(h.holds,'[]'::jsonb),'policy','calendar_days')
 from employee_profiles p left join lateral (
  select sum(days) filter(where state='pending') pending,sum(days) filter(where state='approved') approved,
   jsonb_agg(jsonb_build_object('request_id',request_id,'days',days,'state',state) order by request_id) holds
   from leave_holds where employee_id=p.id and state in ('pending','approved')
 ) h on true where p.id=p_employee_id
$$;
revoke execute on function public.read_leave_balance(uuid) from public,anon,authenticated;
grant execute on function public.read_leave_balance(uuid) to service_role;
notify pgrst,'reload schema';
commit;
